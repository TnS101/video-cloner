"""Publish the isolated combined six-case caption-composition Resolve proof."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
MODULE = "resolve_workspace/modules/caption_composition_resolve_proof.py"
COMPOSITIONS = "data/DZatr0EJt4B/analysis/DZatr0EJt4B_caption_compositions.json"
LIFECYCLE = "data/DZatr0EJt4B/analysis/DZatr0EJt4B_caption_lifecycle_authority.json"
STYLE = "data/DZatr0EJt4B/analysis/DZatr0EJt4B_caption_style.json"
RECIPES = "data/DZatr0EJt4B/analysis/DZatr0EJt4B_caption_animation_recipes_oss002_full.json"
FCPXML = "data/DZatr0EJt4B/davinci/DZatr0EJt4B_mvp_timeline.fcpxml"
REFERENCE_VIDEO = "input/DZatr0EJt4B.mp4"

spec = importlib.util.spec_from_file_location("vc_caption_composition_resolve_proof", ROOT / MODULE)
if spec is None or spec.loader is None:
    raise ImportError(f"cannot_load:{ROOT / MODULE}")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def publish(root: Path = ROOT) -> dict[str, object]:
    root = root.resolve()
    queue = root / ".agent/commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
    active = [path for state in ("pending", "running") for path in (queue / state).glob("*.json")]
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    paths = {
        "compositions": root / COMPOSITIONS,
        "lifecycle": root / LIFECYCLE,
        "style": root / STYLE,
        "recipes": root / RECIPES,
        "fcpxml": root / FCPXML,
        "reference_video": root / REFERENCE_VIDEO,
    }
    if any(not path.is_file() for path in paths.values()):
        raise ValueError("proof_input_missing")
    plans = runtime.build_plans(paths["compositions"], paths["lifecycle"], paths["style"], paths["recipes"])
    now = datetime.now(timezone.utc)
    run_id = f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"
    report = root / ".agent/reports" / runtime.TASK_ID / run_id
    relative_report = report.relative_to(root).as_posix()
    command = {
        "schema_version": 1,
        "task": runtime.TASK_ID,
        "run_id": run_id,
        "module": MODULE,
        "mode": runtime.MODE,
        "status_path": f"{relative_report}/status.json",
        "log_path": f"{relative_report}/run.log",
        "report_path": f"{relative_report}/report.json",
        "payload": {
            "repository_root": str(root),
            "expected_project": runtime.EXPECTED_PROJECT,
            "source_timeline": runtime.SOURCE_TIMELINE,
            "source_timeline_uid": runtime.SOURCE_TIMELINE_UID,
            "proof_timeline": runtime.PROOF_TIMELINE,
            "module_sha256": _sha256(root / MODULE),
            "plan_sha256": runtime.plan_sha256(plans),
            "save_after_verification": True,
            **{
                f"{label}_{suffix}": value
                for label, path in paths.items()
                for suffix, value in (("path", path.relative_to(root).as_posix()), ("sha256", _sha256(path)))
            },
        },
    }
    pending = queue / "pending" / f"{runtime.TASK_ID}_{run_id}.json"
    _write(report / "command.json", command)
    _write(report / "proof_plan.json", {"plan_sha256": runtime.plan_sha256(plans), "plans": plans})
    _write(pending, command)
    return {
        "task_id": runtime.TASK_ID,
        "run_id": run_id,
        "command_path": pending.relative_to(root).as_posix(),
        "proof_timeline": runtime.PROOF_TIMELINE,
        "member_ranges": {row["visual_identity"]: row["target_range"] for row in plans},
    }


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
