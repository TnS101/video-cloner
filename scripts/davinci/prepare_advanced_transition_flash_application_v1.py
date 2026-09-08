#!/usr/bin/env python3
"""Prepare a bounded Resolve command for source-backed Reel #1 flash transitions."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping

TASK_ID = "DZSQH7AUHJT_ADVANCED_TRANSITION_FLASH_APPLICATION_V1"
MODE = "ADVANCED_TRANSITION_FLASH_APPLICATION_V1"
MODULE = "resolve_workspace/modules/advanced_transition_flash_application_v1.py"
VALIDATOR = "scripts/davinci/validate_advanced_transition_flash_application_v1.py"
TRANSITIONS = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_transitions.json"
SOURCE_TIMELINE_NAME = (
    "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_"
    "confirmed74_repair_metrics_v1_occlusion_complete_v4"
)
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_flash_transition_v1"
EXPECTED_TEXTPLUS_COUNT = 114
EXPECTED_FLASH_FRAMES = (96, 377, 426, 454, 758)
SOURCE_PATHS = (
    MODULE,
    VALIDATOR,
    "scripts/davinci/prepare_advanced_transition_flash_application_v1.py",
    TRANSITIONS,
    "resolve_workspace/VC_Agent_Bridge.py",
)
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run_id_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex


def normalized_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def active_commands(root: Path) -> List[Path]:
    rows: List[Path] = []
    for state in ("pending", "running"):
        directory = root / ".agent" / "commands" / state
        if directory.is_dir():
            rows.extend(sorted(directory.glob("*.json")))
    return rows


def build_plan(authority: Mapping[str, Any]) -> Dict[str, Any]:
    transitions = authority.get("transitions")
    if not isinstance(transitions, list):
        raise ValueError("transition_authority")
    selected = [
        row for row in transitions
        if isinstance(row, Mapping)
        and row.get("transition_type") == "flash_cut"
        and row.get("confidence") == "high"
        and row.get("editor_actionable") is True
    ]
    selected.sort(key=lambda row: int(row.get("cut_frame") or -1))
    frames = tuple(int(row.get("cut_frame") or -1) for row in selected)
    if frames != EXPECTED_FLASH_FRAMES:
        raise ValueError(f"flash_authority_frames:{frames}")

    flashes = []
    for index, row in enumerate(selected, start=1):
        cut = int(row["cut_frame"])
        duration = int(row.get("duration_frames") or 0)
        outgoing = int(row.get("outgoing_frames") or 0)
        incoming = int(row.get("incoming_frames") or 0)
        handle = row.get("handle_check") if isinstance(row.get("handle_check"), Mapping) else {}
        if (
            duration != 4
            or outgoing != 2
            or incoming != 2
            or row.get("placement") != "at_cut"
            or handle.get("ok") is not True
            or "white-frame/luma spike near boundary" not in list(row.get("reasons") or [])
        ):
            raise ValueError(f"flash_authority_contract:{index}")
        flashes.append({
            "index": index,
            "name": f"VC_FLASH_{index:03d}_frame_{cut:04d}",
            "transition_type": "flash_cut",
            "confidence": "high",
            "editor_actionable": True,
            "cut_frame": cut,
            "start_frame": cut - outgoing,
            "duration_frames": duration,
            "outgoing_frames": outgoing,
            "incoming_frames": incoming,
            "placement": "at_cut",
            "flash_color": [1.0, 1.0, 1.0],
            "alpha_keyframes": [[0, 0.0], [outgoing, 0.75], [duration - 1, 0.0]],
            "source_strength": row.get("transition_strength"),
            "source_white_ratio_max": ((row.get("scores") or {}).get("white_ratio_max") if isinstance(row.get("scores"), Mapping) else None),
            "source_luma_delta": ((row.get("scores") or {}).get("luma_delta") if isinstance(row.get("scores"), Mapping) else None),
        })
    plan: Dict[str, Any] = {
        "schema": "video_cloner_flash_transition_plan",
        "schema_version": 1,
        "task_id": TASK_ID,
        "architecture_family": "advanced_transition_flash_application_v1",
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "expected_textplus_count": EXPECTED_TEXTPLUS_COUNT,
        "transition_authority_path": TRANSITIONS,
        "transition_authority_sha256": None,
        "flash_count": len(flashes),
        "flashes": flashes,
        "property_contract": {
            "existing_timeline_items_writable": False,
            "clip_boundaries_writable": False,
            "caption_properties_writable": False,
            "occlusion_properties_writable": False,
            "new_top_video_track_only": True,
            "new_flash_carriers_only": True,
            "fusion_background_only": True,
            "flash_color": [1.0, 1.0, 1.0],
            "peak_opacity": 0.75,
        },
        "visual_approval_required": True,
    }
    return plan


def publish(root: Path, run_mode: str, idempotency_of: str | None = None) -> Dict[str, Any]:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file():
        raise ValueError("repository_root")
    if active_commands(root):
        raise ValueError("active_command")
    for relative in SOURCE_PATHS:
        if not (root / relative).is_file():
            raise ValueError(f"source_missing:{relative}")

    authority_path = root / TRANSITIONS
    authority = load_json(authority_path)
    plan = build_plan(authority)
    plan["transition_authority_sha256"] = normalized_sha256(authority_path)
    plan_without_hash = dict(plan)
    plan["plan_sha256"] = canonical_sha256(plan_without_hash)

    if run_mode == "idempotency":
        if not idempotency_of:
            raise ValueError("idempotency_source_run_id")
        prior = root / ".agent" / "reports" / TASK_ID / idempotency_of / "report.json"
        if not prior.is_file():
            raise ValueError("idempotency_source_report")
        prior_value = load_json(prior)
        if prior_value.get("ok") is not True or prior_value.get("run_mode") != "apply":
            raise ValueError("idempotency_source_not_pass")
    else:
        idempotency_of = None

    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)

    run_id = run_id_now()
    report_dir = root / ".agent" / "reports" / TASK_ID / run_id
    if report_dir.exists():
        raise ValueError("run_dir_exists")
    report_dir.mkdir(parents=True)

    plan_path = report_dir / "flash_transition_plan.json"
    write_json(plan_path, plan)

    source_hashes = {relative: normalized_sha256(root / relative) for relative in SOURCE_PATHS}
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
        "source_contract": {
            "algorithm": SOURCE_HASH_ALGORITHM,
            "hashes": source_hashes,
        },
        "flash": {
            "run_mode": run_mode,
            "idempotency_of": idempotency_of,
            "plan_path": str(plan_path.relative_to(root)).replace("/", "\\"),
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "target_timeline_name": TARGET_TIMELINE_NAME,
            "expected_textplus_count": EXPECTED_TEXTPLUS_COUNT,
            "expected_flash_frames": list(EXPECTED_FLASH_FRAMES),
        },
    }
    command_path = queue / "pending" / f"{TASK_ID}_{run_id}.json"
    write_json(command_path, command)
    receipt = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "run_mode": run_mode,
        "idempotency_of": idempotency_of,
        "command_path": str(command_path.relative_to(root)).replace("/", "\\"),
        "plan_path": str(plan_path.relative_to(root)).replace("/", "\\"),
        "manual_action": "Workspace > Scripts > VC_Run_Agent_Task",
        "visual_approval_required": run_mode == "apply",
        "ok": True,
    }
    write_json(report_dir / "publication_receipt.json", receipt)
    return {"command": command, "command_path": command_path, "plan": plan, "receipt": receipt}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-mode", choices=["apply", "idempotency"], default="apply")
    parser.add_argument("--idempotency-of", default=None)
    args = parser.parse_args()
    try:
        result = publish(args.root, args.run_mode, args.idempotency_of)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({
        "ok": True,
        "task_id": TASK_ID,
        "run_id": result["command"]["run_id"],
        "run_mode": args.run_mode,
        "command_path": str(result["command_path"]),
        "plan_sha256": result["plan"]["plan_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
