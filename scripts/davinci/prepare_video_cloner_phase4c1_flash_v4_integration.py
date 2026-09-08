"""Build the exact Phase 4C1 plan and publish one guarded bridge command."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_phase4c1_flash_v4_integration as runtime

MODULE = "resolve_workspace/modules/video_cloner_phase4c1_flash_v4_integration.py"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def run_id() -> str:
    now = datetime.now(timezone.utc)
    return f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"


def build_plan(authority: dict, project_name: str = runtime.PROJECT_NAME, target_name: str = runtime.TARGET_TIMELINE_NAME, contract: dict | None = None, fcpxml_sha256: str = "legacy_phase4c2_compatibility") -> dict:
    legacy = contract is None
    if legacy:
        contract = {"timeline_name": target_name, "clips": [{}] * runtime.EXPECTED_BASE_CLIPS, "duration_frames": runtime.EXPECTED_DURATION, "fps": runtime.EXPECTED_FPS}
    if not project_name or target_name != contract.get("timeline_name") or contract.get("fps") != 24 or not fcpxml_sha256:
        raise ValueError("target_contract")
    source = []
    for row in authority.get("transitions", []):
        if row.get("transition_type") != "flash_cut" or (not legacy and row.get("editor_actionable") is not True):
            continue
        handles = row.get("handle_check")
        if (not legacy and row.get("confidence") != "high") or int(row.get("duration_frames") or 0) != 4 or int(row.get("outgoing_frames") or 0) != 2 or int(row.get("incoming_frames") or 0) != 2 or (isinstance(handles, dict) and handles.get("ok") is not True):
            raise ValueError("transition_authority")
        source.append(row)
    source.sort(key=lambda row: int(row["cut_frame"]))
    if len({int(row["cut_frame"]) for row in source}) != len(source):
        raise ValueError("duplicate_flash_cut")
    flashes = []
    for index, row in enumerate(source, 1):
        cut = int(row["cut_frame"])
        authority_fields = {key: row[key] for key in ("editor_actionable", "confidence", "transition_strength", "placement", "side", "cut_time", "timeline_cut_time", "actionability_reason", "handle_check", "reasons") if key in row}
        authority_fields.setdefault("editor_actionable", True)
        authority_fields.setdefault("confidence", "high")
        flashes.append({"name": f"VC_FLASH_{index:03d}_frame_{cut:04d}", "transition_type": "flash_cut", "cut_frame": cut, "start_frame": cut - 2, "duration_frames": 4, "outgoing_frames": 2, "incoming_frames": 2, "flash_color": [1.0, 1.0, 1.0], "alpha_keyframes": [[0, 0.0], [2, 0.75], [3, 0.0]], "authority": authority_fields})
    plan = {"schema": "video_cloner.phase4c1_flash_v4_plan", "schema_version": 2, "task_id": runtime.TASK_ID, "architecture_family": runtime.V4.ARCHITECTURE_FAMILY, "project_name": project_name, "target_timeline_name": target_name, "protected_timeline_name": None, "protected_signature": None, "artifact": {"timeline_name": contract["timeline_name"], "clip_count": len(contract["clips"]), "duration_frames": contract["duration_frames"], "fps": contract["fps"], "fcpxml_sha256": fcpxml_sha256}, "carrier": {"kind": "transparent_rgba_sequence", "asset_dir": runtime.V4.NEUTRAL_ASSET_DIR_RELATIVE, "pattern": runtime.V4.NEUTRAL_PATTERN, "frame_count": 4, "source_start": 0, "source_end_exclusive": 4, "media_pool_item_name": runtime.V4.NEUTRAL_MEDIA_POOL_ITEM_NAME, "png_sha256": runtime.V4.NEUTRAL_PNG_SHA256, "source_video_pixels_possible": False}, "flashes": flashes}
    plan["plan_sha256"] = runtime.V1.canonical_sha256(plan)
    return plan


def publish(root: Path, authority: Path, fcpxml: Path, fcpxml_sha256: str, project_name: str, target_name: str, mode: str, requested_run_id: str | None = None) -> dict:
    root, authority, fcpxml = root.resolve(), authority.resolve(), fcpxml.resolve()
    if mode not in {"apply", "idempotency"} or runtime.P4B.sha256(fcpxml) != fcpxml_sha256:
        raise ValueError("input_contract")
    contract = runtime.P4B.parse_fcpxml_contract(fcpxml)
    plan = build_plan(json.loads(authority.read_text(encoding="utf-8-sig")), project_name, target_name, contract, fcpxml_sha256)
    runtime.validate_plan(plan)
    rid = requested_run_id or run_id()
    if not re.fullmatch(r"\d{8}T\d{9}Z_[0-9a-f]{32}", rid):
        raise ValueError("run_id")
    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
    if any((queue / state / name).is_file() for state in ("pending", "running") for name in os.listdir(queue / state)):
        raise ValueError("active_command")
    report_rel = f".agent/reports/{runtime.TASK_ID}/{rid}"
    report_dir = root / report_rel
    report_dir.mkdir(parents=True, exist_ok=False)
    plan_path = report_dir / "flash_plan.json"
    write_json(plan_path, plan)
    command = {"schema_version": 1, "task": runtime.TASK_ID, "run_id": rid, "module": MODULE, "mode": runtime.MODE, "status_path": f"{report_rel}/status.json", "log_path": f"{report_rel}/run.log", "report_path": f"{report_rel}/report.json", "payload": {"repository_root": str(root), "report_dir": report_rel, "run_mode": mode, "plan_path": str(plan_path), "plan_sha256": runtime.V4._sha256(plan_path), "fcpxml_path": str(fcpxml), "fcpxml_sha256": fcpxml_sha256, "expected_project": project_name, "target_timeline_name": target_name}}
    pending = queue / "pending" / f"{runtime.TASK_ID}_{rid}.json"
    write_json(pending, command)
    write_json(report_dir / "command.json", command)
    receipt = {"ok": True, "task_id": runtime.TASK_ID, "run_id": rid, "run_mode": mode, "command_path": str(pending.relative_to(root)).replace("\\", "/"), "command_sha256": runtime.P4B.sha256(pending), "plan_path": str(plan_path), "plan_sha256": runtime.V4._sha256(plan_path)}
    write_json(report_dir / "publication_receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--fcpxml", type=Path, required=True)
    parser.add_argument("--fcpxml-sha256", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--target-timeline", required=True)
    parser.add_argument("--run-mode", choices=("apply", "idempotency"), required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    try:
        result = publish(args.root, args.authority, args.fcpxml, args.fcpxml_sha256, args.project, args.target_timeline, args.run_mode, args.run_id)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
