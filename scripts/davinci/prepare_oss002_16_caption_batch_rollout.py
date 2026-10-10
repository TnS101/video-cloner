"""Publish the one approved OSS-002 16-caption batch rollout command."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULE_PATH = ROOT / "resolve_workspace/modules/oss002_16_caption_batch_rollout.py"
spec = importlib.util.spec_from_file_location("vc_oss002_batch", MODULE_PATH)
if spec is None or spec.loader is None:
    raise ImportError(f"cannot_load:{MODULE_PATH}")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)

FCPXML = "data/DZatr0EJt4B/davinci/DZatr0EJt4B_mvp_timeline.fcpxml"
ANIMATION_PLAN = "data/DZatr0EJt4B/analysis/DZatr0EJt4B_caption_animation_plan_step_3C.json"


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
    plan_path, fcpxml_path = root / ANIMATION_PLAN, root / FCPXML
    targets = batch.selected_targets(plan_path)
    remaining = [row for row in targets if row["ordinal"] != batch.ACCEPTED_ORDINAL]
    allocation = batch.allocate_tracks(remaining, {3: [(39, 44)]})
    now = datetime.now(timezone.utc)
    run_id = f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"
    report = root / ".agent" / "reports" / batch.TASK_ID / run_id
    relative_report = report.relative_to(root).as_posix()
    review_manifest = report / "batch_human_review_manifest.json"
    command = {
        "schema_version": 1,
        "task": batch.TASK_ID,
        "run_id": run_id,
        "module": "resolve_workspace/modules/oss002_16_caption_batch_rollout.py",
        "mode": batch.MODE,
        "status_path": f"{relative_report}/status.json",
        "log_path": f"{relative_report}/run.log",
        "report_path": f"{relative_report}/report.json",
        "payload": {
            "repository_root": str(root),
            "expected_project": batch.PROJECT_NAME,
            "target_timeline": batch.TARGET_TIMELINE,
            "accepted_sub008_source_name": batch.ACCEPTED_SOURCE_NAME,
            "accepted_sub008_source_uid": batch.ACCEPTED_SOURCE_UID,
            "expected_selected_count": 16,
            "remaining_target_count": 15,
            "fcpxml_path": FCPXML,
            "fcpxml_sha256": _sha256(fcpxml_path),
            "animation_plan_path": ANIMATION_PLAN,
            "animation_plan_sha256": _sha256(plan_path),
            "review_manifest_path": review_manifest.relative_to(root).as_posix(),
            "save_after_batch_verification": True,
        },
    }
    template = batch.review_manifest(targets, {batch.ACCEPTED_ORDINAL: 3, **allocation}, "PENDING_LIVE_EXECUTION")
    template.update({"run_id": run_id, "project": batch.PROJECT_NAME, "timeline": batch.TARGET_TIMELINE, "production_saved": False})
    pending = queue / "pending" / f"{batch.TASK_ID}_{run_id}.json"
    _write(report / "command.json", command)
    _write(review_manifest, template)
    _write(pending, command)
    return {
        "task_id": batch.TASK_ID,
        "run_id": run_id,
        "command_path": pending.relative_to(root).as_posix(),
        "review_manifest_path": review_manifest.relative_to(root).as_posix(),
    }


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
