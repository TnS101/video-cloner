"""Publish one immutable post-rollback read-only diagnostic command."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from resolve_workspace.modules.video_cloner_phase4b_timeline_application import parse_fcpxml_contract, sha256
from resolve_workspace.modules.video_cloner_phase4c1_post_rollback_readonly_probe import (
    ACTION,
    MODE,
    PROFILE_REEL1,
    PROFILE_REEL2,
    REEL1_SPANS,
    REEL1_ORPHAN_ITEM_NAME,
    REEL1_TIMELINE,
    REEL2_TIMELINE,
    TASK_ID,
)
from scripts.davinci.prepare_video_cloner_phase4c1_flash_location_probe import identity_from_authority

MODULE = "resolve_workspace/modules/video_cloner_phase4c1_post_rollback_readonly_probe.py"
NEUTRAL_RELATIVE = "data/DZsqH7auhjt/davinci/flash_neutral_rgba_v4/rgba_%06d.png"
REEL2_PROTECTION = {
    "timeline_name": REEL2_TIMELINE,
    "occurrence_count": 1,
    "v1_clip_count": 14,
    "duration_frames": 854,
    "fps": 24,
    "video_track_count": 1,
    "v2_absent": True,
    "flash_absent": True,
}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def allocate_run_id() -> str:
    now = datetime.now(timezone.utc)
    return f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"


def build_baseline(fcpxml: Path, expected_hash: str) -> dict[str, object]:
    if sha256(fcpxml) != expected_hash:
        raise ValueError("fcpxml_hash")
    contract = parse_fcpxml_contract(fcpxml)
    return {
        "timeline_name": contract["timeline_name"],
        "clip_count": len(contract["clips"]),
        "duration_frames": contract["duration_frames"],
        "fps": contract["fps"],
        "audio_track_count": 1,
        "source_path": contract["source_path"],
        "clips": contract["clips"],
        "fcpxml_sha256": expected_hash,
    }


def publish(root: Path, project_name: str, target_name: str, authority: Path | None = None, fcpxml: Path | None = None, fcpxml_hash: str | None = None, run_id: str | None = None, diagnostic_profile: str = PROFILE_REEL2) -> dict[str, object]:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file() or not (root / MODULE).is_file() or not project_name or not target_name:
        raise ValueError("repository_contract")
    profile_payload: dict[str, object]
    if diagnostic_profile == PROFILE_REEL2:
        if authority is None or fcpxml is None or fcpxml_hash is None:
            raise ValueError("accepted_baseline")
        baseline = build_baseline(fcpxml.resolve(), fcpxml_hash)
        if baseline["timeline_name"] != target_name or baseline["clip_count"] != 14 or baseline["duration_frames"] != 854 or baseline["fps"] != 24:
            raise ValueError("accepted_baseline")
        identity = identity_from_authority(authority.resolve(), fcpxml.resolve(), fcpxml_hash, project_name, target_name)
        identity_hash = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        profile_payload = {"accepted_baseline": baseline, "expected_flash_identity": identity, "expected_flash_identity_sha256": identity_hash}
    elif diagnostic_profile == PROFILE_REEL1:
        if target_name != REEL1_TIMELINE:
            raise ValueError("reel1_target_contract")
        profile_payload = {
            "target_contract": {
                "timeline_name": REEL1_TIMELINE,
                "occurrence_count": 1,
                "expected_track_index": 26,
                "expected_orphan_item_name": REEL1_ORPHAN_ITEM_NAME,
                "expected_spans": [{"start": start, "end": end} for start, end in REEL1_SPANS],
                "accepted_historical_timeline_name": REEL1_TIMELINE,
            },
            "reel2_protection_contract": dict(REEL2_PROTECTION),
        }
    else:
        raise ValueError("diagnostic_profile")
    run_id = run_id or allocate_run_id()
    if re.fullmatch(r"\d{8}T\d{9}Z_[0-9a-f]{32}", run_id) is None:
        raise ValueError("run_id")
    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
    for state in ("pending", "running"):
        active = sorted((queue / state).glob("*.json"))
        if active:
            raise ValueError(f"active_command:{state}:{active[0].name}")
    if diagnostic_profile == PROFILE_REEL2:
        operation_material = f"{ACTION}\n{project_name}\n{target_name}\n{fcpxml_hash}\n{identity_hash}"
    else:
        contract_hash = hashlib.sha256(json.dumps(profile_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        operation_material = f"{ACTION}\n{diagnostic_profile}\n{project_name}\n{target_name}\n{contract_hash}"
    operation_id = hashlib.sha256(operation_material.encode()).hexdigest()
    relative_report = f".agent/reports/{TASK_ID}/{run_id}"
    report_dir = root / relative_report
    report_dir.mkdir(parents=True, exist_ok=False)
    neutral = str((root / NEUTRAL_RELATIVE).resolve())
    command = {
        "schema_version": 1,
        "task": TASK_ID,
        "run_id": run_id,
        "module": MODULE,
        "mode": MODE,
        "status_path": f"{relative_report}/status.json",
        "log_path": f"{relative_report}/run.log",
        "report_path": f"{relative_report}/report.json",
        "payload": {
            "repository_root": str(root),
            "report_dir": relative_report,
            "action": ACTION,
            "operation_id": operation_id,
            "diagnostic_profile": diagnostic_profile,
            "read_only": True,
            "mutation_permitted": False,
            "expected_project_name": project_name,
            "expected_target_timeline_name": target_name,
            **profile_payload,
            "expected_neutral_paths": {"historical_reel1": neutral, "portable_reel2": neutral},
            "neutral_media_search_tokens": ["VC_FLASH_NEUTRAL_RGBA_V4", "flash_neutral_rgba_v4"],
        },
    }
    pending = queue / "pending" / f"{TASK_ID}_{run_id}.json"
    write_json(pending, command)
    write_json(report_dir / "probe_command.json", command)
    receipt = {
        "ok": True,
        "task_id": TASK_ID,
        "run_id": run_id,
        "operation_id": operation_id,
        "command_path": str(pending.relative_to(root)).replace("\\", "/"),
        "command_sha256": sha256(pending),
        "command_count": 1,
        "manual_action_required": "Workspace > Scripts > VC_Run_Agent_Task exactly once",
    }
    write_json(report_dir / "publication_receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--diagnostic-profile", choices=(PROFILE_REEL2, PROFILE_REEL1), default=PROFILE_REEL2)
    parser.add_argument("--authority", type=Path)
    parser.add_argument("--fcpxml", type=Path)
    parser.add_argument("--fcpxml-sha256")
    parser.add_argument("--project", required=True)
    parser.add_argument("--target-timeline", required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    try:
        result = publish(args.root, args.project, args.target_timeline, args.authority, args.fcpxml, args.fcpxml_sha256, args.run_id, args.diagnostic_profile)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
