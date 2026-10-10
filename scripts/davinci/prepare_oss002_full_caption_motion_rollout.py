"""Publish one accepted OSS-002 full Reel #3 motion rollout command."""
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

MODULE_PATH = ROOT / "resolve_workspace/modules/oss002_full_caption_motion_rollout.py"
spec = importlib.util.spec_from_file_location("vc_oss002_full_rollout", MODULE_PATH)
if spec is None or spec.loader is None:
    raise ImportError(f"cannot_load:{MODULE_PATH}")
rollout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollout)

FCPXML = "data/DZatr0EJt4B/davinci/DZatr0EJt4B_mvp_timeline.fcpxml"
RECIPES = "data/DZatr0EJt4B/analysis/DZatr0EJt4B_caption_animation_recipes_oss002_full.json"
MANIFEST = "data/DZatr0EJt4B/analysis/DZatr0EJt4B_caption_motion_rollout_manifest.json"


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
    manifest_path, recipe_path, fcpxml_path = root / MANIFEST, root / RECIPES, root / FCPXML
    authority, recipes, manifest = rollout._authority(manifest_path)
    if len(authority) != 112 or len(recipes) + int(manifest["counts"]["extraction_failures"]) != 112:
        raise ValueError("full_rollout_authority")
    now = datetime.now(timezone.utc)
    run_id = f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"
    report = root / ".agent" / "reports" / rollout.TASK_ID / run_id
    relative_report = report.relative_to(root).as_posix()
    command = {
        "schema_version": 1,
        "task": rollout.TASK_ID,
        "run_id": run_id,
        "module": "resolve_workspace/modules/oss002_full_caption_motion_rollout.py",
        "mode": rollout.MODE,
        "status_path": f"{relative_report}/status.json",
        "log_path": f"{relative_report}/run.log",
        "report_path": f"{relative_report}/report.json",
        "payload": {
            "repository_root": str(root),
            "expected_project": rollout.rep.EXPECTED_PROJECT,
            "target_timeline": rollout.rep.EXPECTED_TIMELINE,
            "target_timeline_uid": rollout.rep.EXPECTED_TIMELINE_UID,
            "expected_caption_count": 112,
            "expected_video_track_count": 3,
            "expected_existing_nested_count": rollout.EXPECTED_NESTED,
            "manifest_path": MANIFEST,
            "manifest_sha256": _sha256(manifest_path),
            "recipe_path": RECIPES,
            "recipe_sha256": _sha256(recipe_path),
            "fcpxml_path": FCPXML,
            "fcpxml_sha256": _sha256(fcpxml_path),
            "save_after_verification": True,
        },
    }
    pending = queue / "pending" / f"{rollout.TASK_ID}_{run_id}.json"
    _write(report / "command.json", command)
    _write(pending, command)
    return {"task_id": rollout.TASK_ID, "run_id": run_id, "command_path": pending.relative_to(root).as_posix()}


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
