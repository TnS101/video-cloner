"""Publish one Workspace command for the complete Step 3D Text+ rollout."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict

TASK_ID = "DZSQH7AUHJT_STEP_3D_FULL_LIFECYCLE_TEXTPLUS_ROLLOUT_V6"
MODE = "STEP_3D_FULL_LIFECYCLE_TEXTPLUS_ROLLOUT"
MODULE = "resolve_workspace/modules/step_3D_full_lifecycle_textplus_rollout.py"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
SOURCE_PATHS = (
    MODULE,
    "resolve_workspace/modules/step_3D_visual_instance_correction.py",
    "resolve_workspace/modules/step_3D_media_backed_fusion_clone.py",
    "resolve_workspace/modules/step_3D_existing_textplus_clone_probe.py",
    "resolve_workspace/VC_Agent_Bridge.py",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_lifecycle_authority_step_3D_calibrated.json",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_word_instance_tracks_step_3B_6B.json",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_lifecycle_redetection_step_3D.json",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_animation_step_3C_source_targets.json",
    "data/DZsqH7auhjt/davinci/DZsqH7auhjt_resolve_controller_report.json",
)
ACCEPTED_STATE = ".agent/state/latest_accepted.json"
FINAL_TIMELINE_NAME = "DZsqH7auhjt_textplus_full_step_3D_complete_v6_exact_lifecycles"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run_id_now() -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}_{uuid.uuid4().hex}"


def normalized_sha256(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def active_commands(root: Path) -> list[Path]:
    queue = root / ".agent" / "commands"
    out = []
    for state in ("pending", "running"):
        directory = queue / state
        if directory.is_dir():
            out.extend(sorted(directory.glob("*.json")))
    return out


def publish(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file():
        raise ValueError("repository_root")
    active = active_commands(root)
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    for relative in (*SOURCE_PATHS, ACCEPTED_STATE):
        if not (root / relative).is_file():
            raise ValueError(f"source_missing:{relative}")

    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
        if list((queue / state).glob(f"*{TASK_ID}*.json")):
            raise ValueError(f"task_command_exists:{state}")
    task_report_root = root / ".agent" / "reports" / TASK_ID
    if task_report_root.exists():
        raise ValueError("task_report_exists")
    task_report_root.mkdir(parents=True)

    run_id = run_id_now()
    report_dir = task_report_root / run_id
    report_dir.mkdir()
    command = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "module": MODULE,
        "published_at": utc_now(),
        "artifacts_dir": str(report_dir.relative_to(root)).replace("/", "\\"),
        "status_path": str((report_dir / "status.json").relative_to(root)).replace("/", "\\"),
        "log_path": str((report_dir / "run.log").relative_to(root)).replace("/", "\\"),
        "report_path": str((report_dir / "report.json").relative_to(root)).replace("/", "\\"),
        "accepted_state_path": ACCEPTED_STATE.replace("/", "\\"),
        "accepted_state_sha256": raw_sha256(root / ACCEPTED_STATE),
        "source_contract": {
            "version": 1,
            "algorithm": SOURCE_HASH_ALGORITHM,
            "hashes": {relative: normalized_sha256(root / relative) for relative in SOURCE_PATHS},
        },
        "rollout": {
            "timeline_name": FINAL_TIMELINE_NAME,
            "source_timeline_name": "DZsqH7auhjt_textplus_full",
            "source_caption_count": 116,
            "expected_visual_instance_count": 115,
            "represented_cue_count": 116,
            "expected_lane_count": 5,
            "caption_tracks": [3, 4, 5, 6, 7],
            "one_frame_carrier_ids": ["sub_073"],
            "one_frame_visible_range": [521, 522],
            "one_frame_carrier_range": [521, 522],
            "one_frame_carrier_track": 3,
            "one_frame_hidden_tail_frames": 0,
            "append_source_end_padding_frames": 1,
            "expected_exact_lifecycle_instance_count": 115,
            "base_collision_relocation_ids": ["sub_052"],
            "sub_052_original_carrier_track": 4,
            "sub_052_resolved_carrier_track": 7,
            "sub_052_preserved_base_collision": "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052",
            "expected_carrier_track_usage": {"3": 71, "4": 21, "5": 16, "6": 5, "7": 2},
            "expected_animated_instance_count": 8,
            "required_merge_aliases": ["sub_051", "sub_054"],
            "required_merge_style_source": "sub_051",
            "backend": "MediaPool.AppendToTimeline -> ImportFusionComp",
            "cleanup_on_failure": True,
            "keep_on_success": True,
            "expected_success_save_calls": 1,
            "workspace_invocation_count": 1,
        },
    }
    command_name = f"{TASK_ID}_{run_id}.json"
    command_path = queue / "pending" / command_name
    write_json(report_dir / "rollout_command.json", command)
    write_json(command_path, command)
    receipt = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "published_at": command["published_at"],
        "command_path": str(command_path),
        "command_sha256": raw_sha256(command_path),
        "report_dir": str(report_dir),
        "final_timeline_name": FINAL_TIMELINE_NAME,
        "source_contract": command["source_contract"],
        "accepted_state_sha256": command["accepted_state_sha256"],
        "manual_action": "Workspace > Scripts > VC_Run_Agent_Task",
    }
    write_json(report_dir / "publication_receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    receipt = publish(Path(args.root))
    print(json.dumps(receipt, indent=2, sort_keys=True))
    print("MANUAL_ACTION_REQUIRED: Workspace > Scripts > VC_Run_Agent_Task")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
