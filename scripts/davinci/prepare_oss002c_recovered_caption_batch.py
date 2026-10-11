"""Publish one bounded OSS-002C recovered-caption review command."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "resolve_workspace/modules/oss002c_recovered_caption_batch.py"
spec = importlib.util.spec_from_file_location("vc_oss002c_batch", MODULE_PATH)
if spec is None or spec.loader is None:
    raise ImportError(f"cannot_load:{MODULE_PATH}")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)

FCPXML = "data/DZatr0EJt4B/davinci/DZatr0EJt4B_mvp_timeline.fcpxml"
RECIPES = "data/DZatr0EJt4B/analysis/DZatr0EJt4B_caption_animation_recipes_oss002c_recovered.json"
RECOVERY = "data/DZatr0EJt4B/analysis/DZatr0EJt4B_oss002c_cross_authority_recovery.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
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
    recovery, recipes, fcpxml = root / RECOVERY, root / RECIPES, root / FCPXML
    batch._authorities(recovery, recipes)
    now = datetime.now(timezone.utc)
    run_id = f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"
    report = root / ".agent" / "reports" / batch.TASK_ID / run_id
    relative_report = report.relative_to(root).as_posix()
    command = {
        "schema_version": 1,
        "task": batch.TASK_ID,
        "run_id": run_id,
        "module": "resolve_workspace/modules/oss002c_recovered_caption_batch.py",
        "mode": batch.MODE,
        "status_path": f"{relative_report}/status.json",
        "log_path": f"{relative_report}/run.log",
        "report_path": f"{relative_report}/report.json",
        "payload": {
            "repository_root": str(root), "expected_project": batch.rep.EXPECTED_PROJECT,
            "target_timeline": batch.rep.EXPECTED_TIMELINE, "target_timeline_uid": batch.rep.EXPECTED_TIMELINE_UID,
            "expected_caption_count": 112, "expected_video_track_count": 3,
            "expected_existing_nested_count": batch.EXPECTED_EXISTING_NESTED, "target_ordinals": list(batch.TARGET_ORDINALS),
            "recovery_path": RECOVERY, "recovery_sha256": _sha256(recovery),
            "recipe_path": RECIPES, "recipe_sha256": _sha256(recipes),
            "fcpxml_path": FCPXML, "fcpxml_sha256": _sha256(fcpxml), "save_after_verification": True,
        },
    }
    pending = queue / "pending" / f"{batch.TASK_ID}_{run_id}.json"
    _write(report / "command.json", command)
    _write(pending, command)
    return {"task_id": batch.TASK_ID, "run_id": run_id, "command_path": pending.relative_to(root).as_posix()}


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
