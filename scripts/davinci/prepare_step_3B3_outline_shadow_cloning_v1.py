#!/usr/bin/env python3
"""Publish the bounded Step 3B.3 outline/shadow reconciliation command."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping

TASK_ID = "DZSQH7AUHJT_STEP_3B3_OUTLINE_SHADOW_CLONING_V1"
MODE = "STEP_3B3_OUTLINE_SHADOW_CLONING_V1"
PREVIOUS_FAILED_RUN_ID = "20260813T103450539914Z_22ea243b7f3b487db2c75d3f8fe91c0d"
MODULE = "resolve_workspace/modules/step_3B3_outline_shadow_cloning_v1.py"
SOURCE = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1_occlusion_complete_v4"
TARGET = SOURCE + "_outline_shadow_v1"
V4_RUN = ".agent/reports/DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V4/20260812T174800495896Z_07d0e09144764182a5c4b1ec41ca6952"
V4_REPORT = V4_RUN + "/report.json"
V4_PERSISTENT = V4_RUN + "/persistent_readback.json"
V4_TECHNICAL = V4_RUN + "/technical_validation.json"
EFFECT_PLAN = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_effect_mode_plan_step_3B_3C.json"
EFFECT_VALIDATION = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_effect_mode_plan_step_3B_3C_validation.json"
VISUAL_AUTHORITY = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_authority_v4.json"
HISTORICAL_EFFECT_REPORT = "data/DZsqH7auhjt/davinci/DZsqH7auhjt_resolve_effect_mode_step_3B_3C_first_application_report.json"
SOURCE_PATHS = (
    MODULE,
    "resolve_workspace/modules/final_occlusion_composition_v4.py",
    "resolve_workspace/VC_Agent_Bridge.py",
    EFFECT_PLAN,
    EFFECT_VALIDATION,
    VISUAL_AUTHORITY,
    HISTORICAL_EFFECT_REPORT,
    V4_REPORT,
    V4_PERSISTENT,
    V4_TECHNICAL,
)


def _load_runtime(root: Path):
    path = root / MODULE
    spec = importlib.util.spec_from_file_location("vc_step3b3_prepare_runtime", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run_id_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex


def normalized_sha256(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


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




def validate_previous_failed_run(root: Path) -> Dict[str, Any]:
    failed_command = root / ".agent" / "commands" / "failed" / f"{TASK_ID}_{PREVIOUS_FAILED_RUN_ID}.json"
    run = root / ".agent" / "reports" / TASK_ID / PREVIOUS_FAILED_RUN_ID
    report_path = run / "report.json"
    cleanup_path = run / "failure_cleanup.json"
    if not failed_command.is_file() or not report_path.is_file() or not cleanup_path.is_file():
        raise ValueError("previous_failed_run_missing")
    command = load_json(failed_command)
    report = load_json(report_path)
    cleanup = load_json(cleanup_path)
    failures = [str(value) for value in (report.get("failures") or [])]
    if not (
        command.get("task_id") == TASK_ID
        and command.get("run_id") == PREVIOUS_FAILED_RUN_ID
        and report.get("task_id") == TASK_ID
        and report.get("run_id") == PREVIOUS_FAILED_RUN_ID
        and report.get("ok") is False
        and any("unrelated_caption_regression" in value for value in failures)
        and report.get("save_call_count") == 1
        and report.get("failure_cleanup_ok") is True
        and report.get("failed_target_retained") is False
        and cleanup.get("ok") is True
        and cleanup.get("save_call_count") == 1
    ):
        raise ValueError("previous_failed_run_contract")
    return {
        "run_id": PREVIOUS_FAILED_RUN_ID,
        "failure": "unrelated_caption_regression",
        "cleanup_ok": True,
        "target_retained": False,
    }


def validate_v4(report: Mapping[str, Any], persistent: Mapping[str, Any], technical: Mapping[str, Any]) -> Mapping[str, Any]:
    if not (
        report.get("ok") is True
        and report.get("task_id") == "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V4"
        and report.get("target_timeline_name") == SOURCE
        and report.get("final_textplus_count") == 114
        and report.get("caption_mutation_count") == 0
        and report.get("occlusion_mutation_count") == 1
        and report.get("save_call_count") == 1
        and report.get("source_timeline_unchanged") is True
        and report.get("persistent_readback_ok") is True
        and report.get("idempotency_ok") is True
        and report.get("pre_save_pixel_authority_ok") is True
    ):
        raise ValueError("v4_report")
    checks = persistent.get("checks")
    if persistent.get("ok") is not True or not isinstance(checks, Mapping) or not checks or not all(v is True for v in checks.values()):
        raise ValueError("v4_persistent")
    occ = persistent.get("occlusion")
    if not isinstance(occ, Mapping) or occ.get("ok") is not True:
        raise ValueError("v4_occlusion")
    rows = occ.get("rows")
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("v4_occlusion_rows")
    row = rows[0]
    if [row.get("start"), row.get("end"), row.get("track_index")] != [426, 454, 25]:
        raise ValueError("v4_occlusion_geometry")
    tchecks = technical.get("checks")
    if technical.get("ok") is not True or not isinstance(tchecks, Mapping) or not tchecks or not all(v is True for v in tchecks.values()):
        raise ValueError("v4_technical")
    snapshot = persistent.get("target_caption_snapshot")
    if not isinstance(snapshot, Mapping) or snapshot.get("count") != 114 or not snapshot.get("sha256"):
        raise ValueError("v4_target_snapshot")
    return snapshot


def validate_historical_effect(report: Mapping[str, Any]) -> None:
    if report.get("ok") is not True:
        raise ValueError("historical_effect_report")
    rows = report.get("items")
    if not isinstance(rows, list):
        raise ValueError("historical_effect_items")
    come = [row for row in rows if isinstance(row, Mapping) and row.get("name") == "VC_TEXTPLUS_0052_sub_052"]
    if len(come) != 1 or come[0].get("classification_mode") != "outline_and_shadow" or come[0].get("already_correct_before") is not True:
        raise ValueError("historical_come_effect")


def publish(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file():
        raise ValueError("repository_root")
    active = active_commands(root)
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    previous_failure = validate_previous_failed_run(root)
    for relative in SOURCE_PATHS:
        if not (root / relative).is_file():
            raise ValueError(f"source_missing:{relative}")

    runtime = _load_runtime(root)
    report = load_json(root / V4_REPORT)
    persistent = load_json(root / V4_PERSISTENT)
    technical = load_json(root / V4_TECHNICAL)
    accepted_snapshot = validate_v4(report, persistent, technical)
    validate_historical_effect(load_json(root / HISTORICAL_EFFECT_REPORT))

    effect_plan = load_json(root / EFFECT_PLAN)
    effect_validation = load_json(root / EFFECT_VALIDATION)
    visual = load_json(root / VISUAL_AUTHORITY)
    if effect_validation.get("ok") is not True or effect_validation.get("failures"):
        raise ValueError("effect_validation")
    names = [str(value) for value in accepted_snapshot.get("names") or []]
    authority = runtime.build_authority(names, effect_plan, visual)
    audit = runtime.audit_snapshot(accepted_snapshot, authority)
    if runtime.mismatch_signature(audit) != runtime.expected_source_mismatch_signature():
        raise ValueError(f"accepted_effect_preimage:{runtime.mismatch_signature(audit)}")

    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed"):
        directory = queue / state
        directory.mkdir(parents=True, exist_ok=True)
        if list(directory.glob(f"{TASK_ID}_*.json")):
            raise ValueError(f"task_command_exists:{state}")
    failed_dir = queue / "failed"
    failed_dir.mkdir(parents=True, exist_ok=True)
    failed_rows = sorted(failed_dir.glob(f"{TASK_ID}_*.json"))
    expected_failed = failed_dir / f"{TASK_ID}_{PREVIOUS_FAILED_RUN_ID}.json"
    if failed_rows != [expected_failed]:
        raise ValueError(f"unexpected_failed_task_commands:{[path.name for path in failed_rows]}")
    report_root = root / ".agent" / "reports" / TASK_ID
    report_root.mkdir(parents=True, exist_ok=True)
    prior_runs = sorted(path for path in report_root.iterdir() if path.is_dir())
    expected_run = report_root / PREVIOUS_FAILED_RUN_ID
    if prior_runs != [expected_run]:
        raise ValueError(f"unexpected_prior_task_reports:{[path.name for path in prior_runs]}")

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
            "algorithm": "sha256_text_lf_normalized",
            "hashes": {relative: normalized_sha256(root / relative) for relative in SOURCE_PATHS},
        },
        "outline_shadow": {
            "source_timeline_name": SOURCE,
            "repair_of_failed_run_id": PREVIOUS_FAILED_RUN_ID,
            "previous_failure": previous_failure,
            "target_timeline_name": TARGET,
            "accepted_v4_run_id": report.get("run_id"),
            "accepted_caption_snapshot_sha256": accepted_snapshot.get("sha256"),
            "accepted_v4_human_visual_approval_confirmed_by_user": True,
            "expected_textplus_count": 114,
            "authority_counts": authority.get("counts"),
            "expected_source_mismatches": [list(row) for row in runtime.expected_source_mismatch_signature()],
            "authorized_caption": "VC_TEXTPLUS_0052_sub_052",
            "authorized_fields": ["Enabled2", "Enabled3"],
            "authorized_values": {"Enabled2": 1.0, "Enabled3": 1.0},
            "architecture": "monotonic_reconcile_only_current_source_authority_drift",
            "one_save_required": True,
            "one_resolve_invocation_required": True,
            "persistent_readback_required": True,
            "idempotency_required": True,
            "source_timeline_immutable": True,
            "v4_occlusion_immutable": True,
            "visual_approval_required": True,
            "further_rollout_authorized": False,
            "forbidden": [
                "bulk_caption_recreation",
                "caption_detection_changes",
                "Center_mutation",
                "Size_mutation",
                "Font_mutation",
                "Style_mutation",
                "Fill_mutation",
                "timing_or_track_mutation",
                "opacity_or_animation_mutation",
                "occlusion_mutation",
                "rejected_occlusion_v1_v2_v3_source",
                "failed_visual_fidelity_v2_source",
            ],
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
    write_json(report_dir / "outline_shadow_command.json", command)
    return {"command": command, "command_path": command_path, "receipt": receipt, "audit": audit}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        result = publish(args.root)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({
        "ok": True,
        "task_id": TASK_ID,
        "run_id": result["command"]["run_id"],
        "command_path": str(result["command_path"]),
        "accepted_effect_preimage_mismatches": result["audit"]["mismatch_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
