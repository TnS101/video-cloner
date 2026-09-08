#!/usr/bin/env python3
"""Publish exactly one full-reel visual-first baseline rollout command."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict

TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_FULL_ROLLOUT_BASELINE_V1"
MODE = "STEP_3D_VISUAL_FIRST_FULL_ROLLOUT_BASELINE"
MODULE = "resolve_workspace/modules/step_3D_visual_first_full_rollout_baseline.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_full_step_3D_complete_v6_textplus_only"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_baseline_v1"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
AUTHORITY_ROOT = "artifacts/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3"
V6_REPORT_ROOT = (
    ".agent/reports/DZSQH7AUHJT_STEP_3D_FULL_LIFECYCLE_TEXTPLUS_ROLLOUT_V6/"
    "20260806T143907620439Z_857f371ddfb146d7ac136f9087f7d96d"
)
PILOT_RUN_ID = "20260810T011342949336Z_f12b698b68724d27abf91e56be55988f"
PILOT_REPORT_ROOT = f".agent/reports/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_RESOLVE_PILOT_V1/{PILOT_RUN_ID}"
ACCEPTED_STATE = ".agent/state/latest_accepted.json"
SOURCE_COMP_CUES = (
    "sub_006", "sub_018", "sub_032", "sub_033", "sub_034",
    "sub_057", "sub_058", "sub_060", "sub_063", "sub_065",
    "sub_076", "sub_078", "sub_080", "sub_082", "sub_085",
)
SOURCE_PATHS = (
    MODULE,
    "resolve_workspace/modules/step_3D_visual_first_resolve_pilot.py",
    "resolve_workspace/modules/step_3D_full_lifecycle_textplus_rollout.py",
    "resolve_workspace/modules/step_3D_visual_instance_correction.py",
    "resolve_workspace/modules/step_3D_media_backed_fusion_clone.py",
    "resolve_workspace/modules/step_3D_existing_textplus_clone_probe.py",
    "resolve_workspace/VC_Agent_Bridge.py",
    f"{AUTHORITY_ROOT}/visual_authority_script_renderability_v3.json",
    f"{AUTHORITY_ROOT}/script_renderability_validation.json",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_visual_first_script_renderability_correction_v3.json",
    f"{V6_REPORT_ROOT}/rollout_plan.json",
    f"{PILOT_REPORT_ROOT}/pilot_validation.json",
    f"{PILOT_REPORT_ROOT}/visual_review/review_manifest.json",
    *(f"{V6_REPORT_ROOT}/source_comp_exports/{cue}.comp" for cue in SOURCE_COMP_CUES),
)


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


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def active_commands(root: Path) -> list[Path]:
    queue = root / ".agent" / "commands"
    rows: list[Path] = []
    for state in ("pending", "running"):
        directory = queue / state
        if directory.is_dir():
            rows.extend(sorted(directory.glob("*.json")))
    return rows


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

    authority = load_json(root / f"{AUTHORITY_ROOT}/visual_authority_script_renderability_v3.json")
    authority_validation = load_json(root / f"{AUTHORITY_ROOT}/script_renderability_validation.json")
    summary = authority.get("summary") if isinstance(authority.get("summary"), dict) else {}
    boundary = authority.get("next_boundary") if isinstance(authority.get("next_boundary"), dict) else {}
    if authority.get("ok") is not True or authority_validation.get("ok") is not True:
        raise ValueError("authority_not_passed")
    expected_summary = {
        "group_count": 7,
        "visual_token_count": 17,
        "visual_only_component_count": 2,
        "unresolved_component_count": 0,
        "transcript_timing_promoted_count": 0,
        "visual_text_correction_count": 1,
        "provisional_script_font_candidate_count": 2,
    }
    for key, expected in expected_summary.items():
        if summary.get(key) != expected:
            raise ValueError(f"authority_summary:{key}:{summary.get(key)}")
    if boundary.get("full_rollout_allowed") is not False:
        raise ValueError("authority_full_rollout_state")

    pilot_validation = load_json(root / f"{PILOT_REPORT_ROOT}/pilot_validation.json")
    review_manifest = load_json(root / f"{PILOT_REPORT_ROOT}/visual_review/review_manifest.json")
    if pilot_validation.get("ok") is not True or pilot_validation.get("run_id") != PILOT_RUN_ID:
        raise ValueError("pilot_validation")
    if review_manifest.get("ok") is not True or review_manifest.get("group_count") != 7:
        raise ValueError("pilot_review_manifest")
    if review_manifest.get("full_rollout_authorized") is not False:
        raise ValueError("pilot_visual_acceptance_state")

    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
    for state in ("pending", "running", "completed", "failed"):
        if list((queue / state).glob(f"{TASK_ID}_*.json")):
            raise ValueError(f"task_command_exists:{state}")

    report_root = root / ".agent" / "reports" / TASK_ID
    if report_root.exists() and any(path.is_dir() for path in report_root.iterdir()):
        raise ValueError("task_report_exists")
    report_root.mkdir(parents=True, exist_ok=True)

    run_id = run_id_now()
    report_dir = report_root / run_id
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
        "full_rollout_baseline": {
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "target_timeline_name": TARGET_TIMELINE_NAME,
            "authority_manifest": f"{AUTHORITY_ROOT}/visual_authority_script_renderability_v3.json",
            "authority_semantic_sha256": authority.get("semantic_sha256"),
            "pilot_run_id": PILOT_RUN_ID,
            "source_textplus_count": 115,
            "replace_textplus_count": 15,
            "preserve_textplus_count": 100,
            "visual_first_count": 17,
            "expected_final_textplus_count": 117,
            "visual_polish_deferred": True,
            "known_visual_defects_deferred": [
                "animation_direction_and_motion_polish",
                "font_family_and_weight_1_to_1_matching",
                "fine_position_scale_color_and_persistence_polish",
            ],
            "full_rollout_authorized": False,
        },
    }
    command_path = queue / "pending" / f"{TASK_ID}_{run_id}.json"
    write_json(command_path, command)
    receipt = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "command_path": str(command_path.relative_to(root)).replace("/", "\\"),
        "command_sha256": raw_sha256(command_path),
        "published_at": command["published_at"],
        "manual_action_required": "Workspace > Scripts > VC_Run_Agent_Task",
    }
    write_json(report_dir / "publication_receipt.json", receipt)
    write_json(report_dir / "full_rollout_command.json", command)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        result = publish(args.root)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
