#!/usr/bin/env python3
"""Publish exactly one isolated size-only correction for the popping `the`."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping

TASK_ID = "DZSQH7AUHJT_CAPTION_THE_SIZE_POP_FIX_V1"
MODE = "CAPTION_THE_SIZE_POP_FIX_V1"
MODULE = "resolve_workspace/modules/caption_the_size_pop_fix_v1.py"
SOURCE = (
    "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_"
    "repair_metrics_v1_occlusion_complete_v4_motion_fade_v1"
)
TARGET = SOURCE + "_the_size_fix_v1"
SIZE_PLAN = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_font_size_plan_step_3B_2.json"
SIZE_PLAN_SHA256 = "40f6c601f2f72b73c50dc58e942f6b54cdb032163a73d90a58185c9249f61089"
MOTION_RUN = ".agent/reports/DZSQH7AUHJT_CAPTION_MOTION_FADE_APPLICATION_V1/20260813T125513495391Z_0b9611488ec745929a498cc976bcf1ce"
MOTION_REPORT = MOTION_RUN + "/report.json"
MOTION_TECHNICAL = MOTION_RUN + "/technical_validation.json"
MOTION_PERSISTENT = MOTION_RUN + "/persistent_readback.json"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
TARGET_SIZES = {
    "VC_TEXTPLUS_0077_sub_077": 0.089954170778,
    "VC_TEXTPLUS_0079_sub_079": 0.090976377264,
}
SOURCE_PATHS = (
    MODULE,
    "resolve_workspace/modules/caption_motion_fade_application_v1.py",
    "resolve_workspace/modules/final_occlusion_composition_v4.py",
    "resolve_workspace/modules/final_occlusion_composition_v1.py",
    "resolve_workspace/modules/step_3D_visual_instance_correction.py",
    "resolve_workspace/VC_Agent_Bridge.py",
    SIZE_PLAN,
    MOTION_REPORT,
    MOTION_TECHNICAL,
    MOTION_PERSISTENT,
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run_id_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex


def normalized_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()


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


def validate_motion_source(report: Mapping[str, Any], technical: Mapping[str, Any], persistent: Mapping[str, Any]) -> None:
    if (
        report.get("ok") is not True
        or report.get("target_timeline_name") != SOURCE
        or report.get("final_textplus_count") != 114
        or report.get("caption_recreation_count") != 0
        or report.get("size_write_count") != 0
        or report.get("style_write_count") != 0
        or report.get("occlusion_mutation_count") != 0
        or report.get("save_call_count") != 1
        or report.get("persistent_readback_ok") is not True
        or report.get("idempotency_ok") is not True
        or report.get("source_timeline_unchanged") is not True
        or report.get("v4_occlusion_preserved") is not True
    ):
        raise ValueError("motion_source_report")
    checks = technical.get("checks") if isinstance(technical.get("checks"), Mapping) else {}
    if technical.get("ok") is not True or not checks or not all(value is True for value in checks.values()):
        raise ValueError("motion_source_technical")
    pchecks = persistent.get("checks") if isinstance(persistent.get("checks"), Mapping) else {}
    if persistent.get("ok") is not True or not pchecks or not all(value is True for value in pchecks.values()):
        raise ValueError("motion_source_persistent")


def validate_size_plan(path: Path) -> None:
    if hashlib.sha256(path.read_bytes()).hexdigest() != SIZE_PLAN_SHA256:
        raise ValueError("size_plan_hash")
    plan = load_json(path)
    items = plan.get("items")
    if plan.get("ok") is not True or not isinstance(items, list):
        raise ValueError("size_plan")
    rows = {str(row.get("name") or ""): row for row in items if isinstance(row, Mapping)}
    for name, expected in TARGET_SIZES.items():
        row = rows.get(name)
        if not isinstance(row, Mapping):
            raise ValueError(f"size_plan_target:{name}")
        if abs(float(row.get("target_size")) - expected) > 1e-12:
            raise ValueError(f"size_plan_value:{name}")
        metrics = row.get("source_metrics") if isinstance(row.get("source_metrics"), Mapping) else {}
        if metrics.get("source") != "caption_style_event" or not isinstance(metrics.get("bbox"), list):
            raise ValueError(f"size_plan_authority:{name}")


def publish(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file():
        raise ValueError("repository_root")
    active = active_commands(root)
    if active:
        raise ValueError(f"active_command:{active[0].name}")

    validate_motion_source(load_json(root / MOTION_REPORT), load_json(root / MOTION_TECHNICAL), load_json(root / MOTION_PERSISTENT))
    validate_size_plan(root / SIZE_PLAN)
    for relative in SOURCE_PATHS:
        if not (root / relative).is_file():
            raise ValueError(f"source_missing:{relative}")

    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        directory = queue / state
        directory.mkdir(parents=True, exist_ok=True)
        if list(directory.glob(f"{TASK_ID}_*.json")):
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
        "source_contract": {
            "version": 1,
            "algorithm": SOURCE_HASH_ALGORITHM,
            "hashes": {relative: normalized_sha256(root / relative) for relative in SOURCE_PATHS},
        },
        "the_size_fix": {
            "source_timeline_name": SOURCE,
            "target_timeline_name": TARGET,
            "expected_textplus_count": 114,
            "target_sizes": {name: TARGET_SIZES[name] for name in sorted(TARGET_SIZES)},
            "target_caption_count": 2,
            "only_size_mutation_authorized": True,
            "center_mutation_authorized": False,
            "opacity_mutation_authorized": False,
            "style_mutation_authorized": False,
            "timing_track_mutation_authorized": False,
            "caption_recreation_authorized": False,
            "occlusion_mutation_authorized": False,
            "accepted_motion_fade_source_must_persist": True,
            "accepted_v4_occlusion_must_persist": True,
            "one_save_required": True,
            "one_resolve_invocation_required": True,
            "persistent_readback_required": True,
            "idempotency_required": True,
            "visual_approval_required": True,
            "further_rollout_authorized": False,
        },
    }
    command_path = queue / "pending" / f"{TASK_ID}_{run_id}.json"
    write_json(command_path, command)
    receipt = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "command_path": str(command_path.relative_to(root)).replace("/", "\\"),
        "manual_action": "Workspace > Scripts > VC_Run_Agent_Task",
        "manual_action_count": 1,
        "visual_approval_required": True,
        "ok": True,
    }
    write_json(report_dir / "publication_receipt.json", receipt)
    write_json(report_dir / "the_size_fix_command.json", command)
    return {"command": command, "command_path": command_path, "receipt": receipt}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        result = publish(args.root)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "task_id": TASK_ID, "run_id": result["command"]["run_id"], "command_path": str(result["command_path"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
