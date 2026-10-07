"""Publish one immutable read-only Reel #2 social-target preflight command."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "VIDEO_CLONER_STEP4_REEL2_SOCIAL_TARGET_READONLY_PREFLIGHT_V1"
MODE = "step4_reel2_social_target_readonly_preflight"
MODULE = "resolve_workspace/modules/video_cloner_step4_reel2_social_target_readonly_preflight.py"
BASE = "resolve_workspace/modules/video_cloner_phase6_textplus_application.py"
ACCEPTED = ".agent/reports/VIDEO_CLONER_PHASE6_OFFLINE_TIMELINE_LIVE_APPLICATION_V1/PHASE6_V1_PROVENANCE_SAVE_20260912T181724287Z_41b3b9ee155d4732bfd3a4891ae081eb/report.json"
EXPORTED = ".agent/reports/VIDEO_CLONER_PHASE6_OFFLINE_TIMELINE_LIVE_APPLICATION_V1/PHASE6_V1_EXPORT_FINALIZE_20260912T175637672Z_36f3a798745340e0a7916c4b2cac7a71/live_target_pre_save.fcpxml/Info.fcpxml"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def publish(root: Path = ROOT) -> dict[str, object]:
    root = root.resolve()
    for relative in (MODULE, BASE, ACCEPTED, EXPORTED):
        if not (root / relative).is_file():
            raise ValueError(f"required_file:{relative}")
    state = json.loads((root / ".agent/state/resolve_bridge_installation.json").read_text(encoding="utf-8-sig"))
    config_path = Path(str(state.get("config_path") or ""))
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if Path(str(config.get("repository_root") or "")).resolve() != root or config.get("command_queue") != ".agent\\commands":
        raise ValueError("bridge_config")
    queue = root / ".agent/commands"
    for name in ("pending", "running", "completed", "failed"):
        (queue / name).mkdir(parents=True, exist_ok=True)
    for name in ("pending", "running"):
        active = list((queue / name).glob("*.json"))
        if active:
            raise ValueError(f"active_command:{name}:{active[0].name}")
    now = datetime.now(timezone.utc)
    run_id = f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"
    report_relative = f".agent/reports/{TASK_ID}/{run_id}"
    report_dir = root / report_relative
    report_dir.mkdir(parents=True, exist_ok=False)
    command = {
        "schema_version": 1, "task_id": TASK_ID, "run_id": run_id,
        "module": MODULE, "mode": MODE,
        "status_path": f"{report_relative}/status.json",
        "log_path": f"{report_relative}/run.log",
        "report_path": f"{report_relative}/report.json",
        "payload": {
            "repository_root": str(root), "read_only": True,
            "accepted_report_path": ACCEPTED, "accepted_report_sha256": sha256(root / ACCEPTED),
            "exported_fcpxml_path": EXPORTED, "exported_fcpxml_sha256": sha256(root / EXPORTED),
            "expected_project": "New Project 1",
            "target_timeline_name": "DcJRJtUKScu_offline_timeline_v1",
            "expected_timeline_uid": "4ad2a3c3-031c-464d-96aa-76a045608ad6",
            "expected_item_name": "VC Caption 0045 - social,",
            "expected_track": 2, "expected_start": 365, "expected_end": 376,
            "expected_text": "social,", "canonical_window": [359, 383],
            "local_animation_range": [0, 23],
            "mutation_permitted": False, "save_project": False,
            "create_permitted": False, "delete_permitted": False,
            "title_write_permitted": False, "modifier_write_permitted": False,
            "keyframe_write_permitted": False, "import_permitted": False,
            "relink_permitted": False, "replace_permitted": False,
            "timeline_selection_permitted": False,
        },
    }
    filename = f"{TASK_ID}_{run_id}.json"
    pending = queue / "pending" / filename
    write_json(pending, command)
    write_json(report_dir / "command.json", command)
    receipt = {
        "ok": True, "task_id": TASK_ID, "run_id": run_id,
        "command_path": str(pending.relative_to(root)),
        "config_path": str(config_path), "command_count": 1,
    }
    write_json(report_dir / "publication_receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
