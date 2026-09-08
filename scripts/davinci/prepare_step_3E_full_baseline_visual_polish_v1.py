#!/usr/bin/env python3
"""Publish exactly one Step 3E.3 17-token V4 full-baseline polish command."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

TASK_ID = "DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1"
MODE = "STEP_3E_FULL_BASELINE_VISUAL_POLISH"
MODULE = "resolve_workspace/modules/step_3E_full_baseline_visual_polish_v1.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_g02_fontmetrics_v1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_17tokens_v1"

V4_AUTHORITY = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_authority_v4.json"
BASELINE_PLAN = (
    ".agent/reports/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_FULL_ROLLOUT_BASELINE_V1/"
    "20260810T080927254297Z_befb7b9f1474440fb817520c47ba8cd3/full_rollout_plan.json"
)
GROUP02_CONTRACT = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_group02_font_metrics_v1.json"
GROUP02_TASK = "DZSQH7AUHJT_STEP_3E_GROUP02_FONT_METRICS_POLISH_V1"
GROUP02_RUN = "20260810T095011303809Z_9abadb9f9cb447e28b357e2c11ebeed1"
GROUP02_ROOT = f".agent/reports/{GROUP02_TASK}/{GROUP02_RUN}"
ACCEPTED_STATE = ".agent/state/latest_accepted.json"
TEMPLATE_COMP = (
    ".agent/reports/DZSQH7AUHJT_STEP_3D_FULL_LIFECYCLE_TEXTPLUS_ROLLOUT_V6/"
    "20260806T143907620439Z_857f371ddfb146d7ac136f9087f7d96d/source_comp_exports/sub_018.comp"
)
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"

SOURCE_PATHS = (
    MODULE,
    V4_AUTHORITY,
    BASELINE_PLAN,
    GROUP02_CONTRACT,
    "resolve_workspace/modules/step_3D_visual_first_full_rollout_baseline.py",
    "resolve_workspace/modules/step_3D_visual_first_resolve_pilot.py",
    "resolve_workspace/modules/step_3D_full_lifecycle_textplus_rollout.py",
    "resolve_workspace/modules/step_3D_visual_instance_correction.py",
    "resolve_workspace/VC_Agent_Bridge.py",
    f"{GROUP02_ROOT}/report.json",
    f"{GROUP02_ROOT}/persistent_readback.json",
)

EXPECTED_GROUPS = 7
EXPECTED_TOKENS = 17
EXPECTED_FRAMES = 397


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run_id_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex


def normalized_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def active_commands(root: Path) -> List[Path]:
    rows: List[Path] = []
    queue = root / ".agent" / "commands"
    for state in ("pending", "running"):
        directory = queue / state
        if directory.is_dir():
            rows.extend(sorted(directory.glob("*.json")))
    return rows


def authority_counts(authority: Dict[str, Any]) -> tuple[int, int, int]:
    groups = authority.get("groups") if isinstance(authority.get("groups"), list) else []
    tokens = []
    for group in groups:
        if isinstance(group, dict) and isinstance(group.get("tokens"), list):
            tokens.extend(group["tokens"])
    frames = sum(len(row.get("frame_path") or []) for row in tokens if isinstance(row, dict))
    return len(groups), len(tokens), frames


def publish(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file():
        raise ValueError("repository_root")
    active = active_commands(root)
    if active:
        raise ValueError(f"active_command:{active[0].name}")

    for relative in (*SOURCE_PATHS, ACCEPTED_STATE, TEMPLATE_COMP):
        if not (root / relative).is_file():
            raise ValueError(f"source_missing:{relative}")

    authority = load_json(root / V4_AUTHORITY)
    groups, tokens, frames = authority_counts(authority)
    policy = authority.get("authority_policy") if isinstance(authority.get("authority_policy"), dict) else {}
    boundary = authority.get("next_boundary") if isinstance(authority.get("next_boundary"), dict) else {}
    if authority.get("task_id") != "DZSQH7AUHJT_STEP_3E_TEMPORAL_VISUAL_AUTHORITY_V4" or authority.get("ok") is not True:
        raise ValueError("v4_authority")
    if (groups, tokens, frames) != (EXPECTED_GROUPS, EXPECTED_TOKENS, EXPECTED_FRAMES):
        raise ValueError(f"v4_counts:{groups}:{tokens}:{frames}")
    if policy.get("primary_authority") != "source_video_pixels" or policy.get("transcript_timing_authority") is not False:
        raise ValueError("v4_authority_policy")
    if policy.get("full_rollout_authorized") is not False or boundary.get("full_baseline_polish_patch_allowed") is not True:
        raise ValueError("v4_boundary")

    baseline = load_json(root / BASELINE_PLAN)
    instances = baseline.get("visual_first_instances") if isinstance(baseline.get("visual_first_instances"), list) else []
    if baseline.get("ok") is not True or len(instances) != EXPECTED_TOKENS:
        raise ValueError("baseline_plan")
    tracks = sorted(int(row.get("target_track") or 0) for row in instances if isinstance(row, dict))
    if tracks != list(range(8, 25)):
        raise ValueError("baseline_tracks")

    group02 = load_json(root / GROUP02_CONTRACT)
    group02_plans = group02.get("plans") if isinstance(group02.get("plans"), list) else []
    if group02.get("task_id") != GROUP02_TASK or group02.get("ok") is not True or len(group02_plans) != 2:
        raise ValueError("group02_contract")
    if {str(row.get("visual_token_id") or "") for row in group02_plans} != {"vf_02_already", "vf_02_decorative_glyph"}:
        raise ValueError("group02_tokens")

    g02_report = load_json(root / f"{GROUP02_ROOT}/report.json")
    g02_persistent = load_json(root / f"{GROUP02_ROOT}/persistent_readback.json")
    if (
        g02_report.get("ok") is not True
        or g02_report.get("run_id") != GROUP02_RUN
        or g02_report.get("target_timeline_name") != SOURCE_TIMELINE_NAME
        or g02_report.get("final_textplus_count") != 117
        or g02_report.get("save_call_count") != 1
    ):
        raise ValueError("group02_report")
    if g02_persistent.get("ok") is not True or not all((g02_persistent.get("checks") or {}).values()):
        raise ValueError("group02_persistent")

    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
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
        "polish": {
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "target_timeline_name": TARGET_TIMELINE_NAME,
            "authority": V4_AUTHORITY,
            "authority_semantic_sha256": authority.get("semantic_sha256"),
            "visual_token_count": EXPECTED_TOKENS,
            "explicit_frame_row_count": EXPECTED_FRAMES,
            "expected_unchanged_textplus_count": 100,
            "expected_final_textplus_count": 117,
            "transcript_timing_authority": False,
            "visual_approval_required": True,
            "remaining_caption_rollout_authorized": False,
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
    write_json(report_dir / "polish_command.json", command)
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
