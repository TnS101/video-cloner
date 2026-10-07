"""Validate immutable authorities and publish one guarded Step 6A bridge command."""
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

from resolve_workspace.modules import video_cloner_step6a_flash_integration as runtime

MODULE = "resolve_workspace/modules/video_cloner_step6a_flash_integration.py"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def new_run_id() -> str:
    now = datetime.now(timezone.utc)
    return f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"


def transition_hints(planning: dict) -> list[dict]:
    rows = []
    for command in planning.get("timeline", []):
        for operation in command.get("operations", []):
            if operation.get("operation") == "transition_hint":
                rows.append(operation.get("parameters") or {})
    return rows


def build_plan(detector: dict, planning: dict) -> dict:
    if float(detector.get("fps") or 0) != 24.0 or float((planning.get("source") or {}).get("fps") or 0) != 24.0:
        raise ValueError("authority_fps")
    detector_rows = [row for row in detector.get("transitions", []) if row.get("transition_type") == "flash_cut" and row.get("editor_actionable") is True]
    if len(detector_rows) != 1:
        raise ValueError(f"executable_detector_rows:{len(detector_rows)}")
    row = detector_rows[0]
    if any((int(row.get("cut_frame") or -1) != 596, int(row.get("duration_frames") or -1) != 4, int(row.get("outgoing_frames") or -1) != 2, int(row.get("incoming_frames") or -1) != 2, row.get("confidence") != "high", (row.get("handle_check") or {}).get("ok") is not True)):
        raise ValueError("accepted_detector_flash")
    hints = transition_hints(planning)
    accepted_hints = [hint for hint in hints if hint.get("transition_type") == "flash_cut" and int(hint.get("cut_frame") or -1) == 596]
    if len(hints) != 1 or len(accepted_hints) != 1:
        raise ValueError("planning_corroboration")
    flash = {"transition_type": "flash_cut", "confidence": "high", "editor_actionable": True, "start_frame": 594, "cut_frame": 596, "end_frame_exclusive": 598, "duration_frames": 4, "outgoing_frames": 2, "incoming_frames": 2, "alpha_keyframes": [[0, 0.0], [2, 0.75], [3, 0.0]], "detector_authority": {key: row.get(key) for key in ("from_shot", "to_shot", "cut_time", "cut_frame", "timeline_cut_frame", "confidence", "transition_strength", "duration_frames", "outgoing_frames", "incoming_frames", "handle_check", "editor_actionable", "actionability_reason", "reasons")}, "planning_corroboration": {"cut_frame": 596, "transition_type": "flash_cut", "historical_duration_frames": int(accepted_hints[0].get("duration_frames") or 0), "execution_duration_source": "accepted_detector_authority"}}
    plan = {"schema": "video_cloner.step6a_gold_flash_plan", "schema_version": 1, "task_id": runtime.TASK_ID, "project_name": runtime.PROJECT_NAME, "gold_timeline_name": runtime.GOLD_TIMELINE_NAME, "target_timeline_name": runtime.TARGET_TIMELINE_NAME, "gold_drt_path": runtime.GOLD_DRT_RELATIVE, "gold_drt_sha256": runtime.GOLD_DRT_SHA256, "detector_path": runtime.DETECTOR_RELATIVE, "detector_sha256": runtime.DETECTOR_SHA256, "planning_path": runtime.PLANNING_RELATIVE, "planning_sha256": runtime.PLANNING_SHA256, "reel_mapping": {"fps": 24, "start_frame": 594, "cut_frame": 596, "end_frame_exclusive": 598, "duration_frames": 4}, "carrier": {"kind": "transparent_rgba_sequence", "asset_dir": runtime.V4.NEUTRAL_ASSET_DIR_RELATIVE, "pattern": runtime.V4.NEUTRAL_PATTERN, "frame_count": 4, "media_pool_item_name": runtime.V4.NEUTRAL_MEDIA_POOL_ITEM_NAME, "png_sha256": runtime.V4.NEUTRAL_PNG_SHA256, "source_video_pixels_possible": False}, "flashes": [flash], "non_executable_transition_types": sorted({str(candidate.get("transition_type")) for candidate in detector.get("transitions", []) if candidate is not row})}
    plan["plan_sha256"] = runtime.V1.canonical_sha256(plan)
    runtime.validate_plan(plan)
    return plan


def publish(root: Path, mode: str, requested_run_id: str | None = None) -> dict:
    root = root.resolve()
    if mode not in {"apply", "idempotency"}:
        raise ValueError("run_mode")
    hashes = runtime.verify_input_hashes(root)
    if not hashes["ok"]:
        raise ValueError("authority_hash")
    detector = json.loads((root / runtime.DETECTOR_RELATIVE).read_text(encoding="utf-8-sig"))
    planning = json.loads((root / runtime.PLANNING_RELATIVE).read_text(encoding="utf-8-sig"))
    plan = build_plan(detector, planning)
    rid = requested_run_id or new_run_id()
    if not re.fullmatch(r"\d{8}T\d{9}Z_[0-9a-f]{32}", rid):
        raise ValueError("run_id")
    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
    active = [path for state in ("pending", "running") for path in (queue / state).iterdir() if path.is_file()]
    if active:
        raise ValueError("active_command")
    report_rel = f".agent/reports/{runtime.TASK_ID}/{rid}"
    report_dir = root / report_rel
    report_dir.mkdir(parents=True, exist_ok=False)
    plan_path = report_dir / "step6a_flash_plan.json"
    write_json(plan_path, plan)
    command = {"schema_version": 1, "task": runtime.TASK_ID, "run_id": rid, "module": MODULE, "mode": runtime.MODE, "status_path": f"{report_rel}/status.json", "log_path": f"{report_rel}/run.log", "report_path": f"{report_rel}/report.json", "payload": {"repository_root": str(root), "report_dir": report_rel, "run_mode": mode, "plan_path": str(plan_path), "plan_sha256": runtime.sha256(plan_path), "expected_project": runtime.PROJECT_NAME, "gold_timeline_name": runtime.GOLD_TIMELINE_NAME, "target_timeline_name": runtime.TARGET_TIMELINE_NAME}}
    pending = queue / "pending" / f"{runtime.TASK_ID}_{rid}.json"
    write_json(pending, command)
    write_json(report_dir / "command.json", command)
    receipt = {"ok": True, "task_id": runtime.TASK_ID, "run_id": rid, "run_mode": mode, "command_path": str(pending.relative_to(root)).replace("\\", "/"), "command_sha256": runtime.sha256(pending), "plan_path": str(plan_path), "plan_sha256": runtime.sha256(plan_path), "authority_verification": hashes}
    write_json(report_dir / "publication_receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-mode", choices=("apply", "idempotency"), required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    try:
        print(json.dumps(publish(args.root, args.run_mode, args.run_id), indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
