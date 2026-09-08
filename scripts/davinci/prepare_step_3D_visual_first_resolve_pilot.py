#!/usr/bin/env python3
"""Publish one Workspace command for the seven-window visual-first Resolve pilot."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict

TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_RESOLVE_PILOT_V1"
MODE = "STEP_3D_VISUAL_FIRST_RESOLVE_PILOT"
MODULE = "resolve_workspace/modules/step_3D_visual_first_resolve_pilot.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_full_step_3D_complete_v6_textplus_only"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_pilot_v1"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
AUTHORITY_ROOT = "artifacts/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3"
V6_REPORT_ROOT = (
    ".agent/reports/DZSQH7AUHJT_STEP_3D_FULL_LIFECYCLE_TEXTPLUS_ROLLOUT_V6/"
    "20260806T143907620439Z_857f371ddfb146d7ac136f9087f7d96d"
)
SOURCE_PATHS = (
    MODULE,
    "resolve_workspace/modules/step_3D_full_lifecycle_textplus_rollout.py",
    "resolve_workspace/modules/step_3D_visual_instance_correction.py",
    "resolve_workspace/modules/step_3D_media_backed_fusion_clone.py",
    "resolve_workspace/modules/step_3D_existing_textplus_clone_probe.py",
    "resolve_workspace/VC_Agent_Bridge.py",
    "scripts/analysis/build_step_3D_visual_first_resolve_pilot_review.py",
    f"{AUTHORITY_ROOT}/visual_authority_script_renderability_v3.json",
    f"{AUTHORITY_ROOT}/script_renderability_validation.json",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_visual_first_script_renderability_correction_v3.json",
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_font_candidates_unsafe_v1_0.json",
    f"{V6_REPORT_ROOT}/source_comp_exports/sub_006.comp",
    f"{V6_REPORT_ROOT}/source_comp_exports/sub_018.comp",
    f"{V6_REPORT_ROOT}/source_comp_exports/sub_032.comp",
    f"{V6_REPORT_ROOT}/source_comp_exports/sub_033.comp",
    f"{V6_REPORT_ROOT}/source_comp_exports/sub_034.comp",
    f"{V6_REPORT_ROOT}/source_comp_exports/sub_057.comp",
    f"{V6_REPORT_ROOT}/source_comp_exports/sub_058.comp",
    f"{V6_REPORT_ROOT}/source_comp_exports/sub_060.comp",
    f"{V6_REPORT_ROOT}/source_comp_exports/sub_063.comp",
    f"{V6_REPORT_ROOT}/source_comp_exports/sub_065.comp",
    f"{V6_REPORT_ROOT}/source_comp_exports/sub_076.comp",
    f"{V6_REPORT_ROOT}/source_comp_exports/sub_078.comp",
    f"{V6_REPORT_ROOT}/source_comp_exports/sub_080.comp",
    f"{V6_REPORT_ROOT}/source_comp_exports/sub_082.comp",
    f"{V6_REPORT_ROOT}/source_comp_exports/sub_085.comp",
)
ACCEPTED_STATE = ".agent/state/latest_accepted.json"
REPAIRABLE_PRIOR_FAILED_RUNS = (
    (
        "20260807T083110450377Z_d8dd181bc5d34be6a45d15daa50f7024",
        "RuntimeError: apply_token:vf_01_nineteen",
    ),
    (
        "20260807T094714666190Z_ac182f6bc465456fbcd600320b079e5f",
        "RuntimeError: apply_token:vf_01_nineteen:static",
    ),
    (
        "20260809T144650400615Z_70c9125325594753a6e6a95b983fe52a",
        "RuntimeError: render:source_only:RuntimeError: set_render_settings",
    ),
    (
        "20260809T165453808390Z_d2eb9621717e4f508d4f45f247c710dd",
        "RuntimeError: render:generated_only:RuntimeError: render_failed:failed",
    ),
    (
        "20260809T194731461513Z_be03a73d7b2546fb97f3160ec60eec52",
        "RuntimeError: render:generated_only:RuntimeError: render_candidates_exhausted:MP4/H264_NVIDIA:RuntimeError: render_failed:failed|MP4/H264:RuntimeError: render_failed:failed|MP4/AV1YUV420_10_NVIDIA:RuntimeError: configure_review_render|MP4/AV1YUV420_8_NVIDIA:RuntimeError: configure_review_render|MP4/H265_NVIDIA:RuntimeError: render_failed:failed|MP4/H265:RuntimeError: render_failed:failed|MP4/APVYUV422_10:RuntimeError: render_failed:failed",
    ),
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


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


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
    if summary.get("group_count") != 7 or summary.get("visual_token_count") != 17:
        raise ValueError("authority_counts")
    if summary.get("unresolved_component_count") != 0 or summary.get("placeholder_count") != 0:
        raise ValueError("authority_unresolved")
    if summary.get("transcript_timing_promoted_count") != 0:
        raise ValueError("transcript_timing_promoted")
    if summary.get("visual_text_correction_count") != 1:
        raise ValueError("authority_visual_text_correction_count")
    if summary.get("provisional_script_font_candidate_count") != 2:
        raise ValueError("authority_script_font_candidate_count")
    if boundary.get("resolve_action_allowed") is not True or boundary.get("scope") != "seven_windows_only":
        raise ValueError("authority_boundary")
    if boundary.get("full_rollout_allowed") is not False:
        raise ValueError("full_rollout_authorized")

    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)

    for state in ("pending", "running", "completed"):
        if list((queue / state).glob(f"{TASK_ID}_*.json")):
            raise ValueError(f"task_command_exists:{state}")

    expected_failed_runs = [run_id for run_id, _ in REPAIRABLE_PRIOR_FAILED_RUNS]
    expected_failed_names = [f"{TASK_ID}_{run_id}.json" for run_id in expected_failed_runs]
    failed_commands = sorted((queue / "failed").glob(f"{TASK_ID}_*.json"))
    if failed_commands:
        if [path.name for path in failed_commands] != sorted(expected_failed_names):
            raise ValueError("unexpected_prior_failed_run")
        for path, expected_run_id in zip(failed_commands, sorted(expected_failed_runs)):
            prior_command = load_json(path)
            if prior_command.get("run_id") != expected_run_id:
                raise ValueError("prior_failed_run_id")

    task_report_root = root / ".agent" / "reports" / TASK_ID
    if task_report_root.exists():
        existing_runs = sorted(path.name for path in task_report_root.iterdir() if path.is_dir())
        if existing_runs:
            if existing_runs != sorted(expected_failed_runs) or not failed_commands:
                raise ValueError("unexpected_task_report_run")
            expected_errors = dict(REPAIRABLE_PRIOR_FAILED_RUNS)
            for prior_run_id in existing_runs:
                prior_report = load_json(task_report_root / prior_run_id / "report.json")
                prior_cleanup = load_json(task_report_root / prior_run_id / "failure_cleanup.json")
                if prior_report.get("ok") is not False or prior_report.get("error") != expected_errors[prior_run_id]:
                    raise ValueError("prior_failed_report")
                if prior_cleanup.get("ok") is not True or prior_cleanup.get("target_deleted") is not True:
                    raise ValueError("prior_failed_cleanup")
        elif failed_commands:
            raise ValueError("prior_failed_report_missing")
    elif failed_commands:
        raise ValueError("prior_failed_report_missing")
    else:
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
        "pilot": {
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "target_timeline_name": TARGET_TIMELINE_NAME,
            "authority_manifest": f"{AUTHORITY_ROOT}/visual_authority_script_renderability_v3.json",
            "authority_semantic_sha256": authority.get("semantic_sha256"),
            "group_count": 7,
            "visual_token_count": 17,
            "visual_only_component_count": 2,
            "transcript_timing_promoted_count": 0,
            "render_frame_range": [176, 692],
            "render_modes": ["source_only", "generated_only", "alignment_overlay"],
            "render_resolution": [540, 960],
            "keep_on_success": True,
            "cleanup_on_failure": True,
            "expected_save_calls": 1,
            "full_rollout_authorized": False,
            "visual_approval_required": True,
        },
    }
    command_path = queue / "pending" / f"{TASK_ID}_{run_id}.json"
    write_json(report_dir / "pilot_command.json", command)
    write_json(command_path, command)
    receipt = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "published_at": command["published_at"],
        "command_path": str(command_path),
        "command_sha256": raw_sha256(command_path),
        "report_dir": str(report_dir),
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "authority_semantic_sha256": authority.get("semantic_sha256"),
        "manual_action": "Workspace > Scripts > VC_Run_Agent_Task",
        "workspace_invocation_limit": 1,
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
