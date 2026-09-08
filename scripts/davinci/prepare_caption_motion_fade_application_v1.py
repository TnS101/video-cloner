#!/usr/bin/env python3
"""Build authority and publish exactly one caption motion/fade Resolve command."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping

TASK_ID = "DZSQH7AUHJT_CAPTION_MOTION_FADE_APPLICATION_V1"
MODE = "CAPTION_MOTION_FADE_APPLICATION_V1"
MODULE = "resolve_workspace/modules/caption_motion_fade_application_v1.py"
AUTHORITY_BUILDER = "scripts/analysis/build_caption_motion_fade_authority_v1.py"
AUTHORITY = "artifacts/DZSQH7AUHJT_CAPTION_MOTION_FADE_APPLICATION_V1/caption_motion_fade_authority_v1.json"
SOURCE_TIMELINE = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1_occlusion_complete_v4"
TARGET_TIMELINE = SOURCE_TIMELINE + "_motion_fade_v1"
VF = "artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_AUTHORITY_V2/visual_fidelity_authority_v2.json"
VF_HASH = "6f7cdf265dcb18611e7f6326d7d12de7a3dade7b2a7b6d33e1d406d5645ca6f5"
V4_AUTHORITY = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_authority_v4.json"
PROTECTED = ".agent/reports/DZSQH7AUHJT_STEP_3E_FULL_BASELINE_VISUAL_POLISH_V1/20260810T110941414962Z_97d2818ffaf14c26b29ca6207316aa0d/persistent_readback.json"
V4_REPORT = ".agent/reports/DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V4/20260812T174800495896Z_07d0e09144764182a5c4b1ec41ca6952/report.json"
V4_TECHNICAL = ".agent/reports/DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V4/20260812T174800495896Z_07d0e09144764182a5c4b1ec41ca6952/technical_validation.json"
B33 = "artifacts/DZSQH7AUHJT_STEP_3B3_OUTLINE_SHADOW_AUTHORITY_RECONCILIATION_V2/effective_authority_validation.json"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
SOURCE_PATHS = (
    MODULE,
    AUTHORITY_BUILDER,
    AUTHORITY,
    VF,
    V4_AUTHORITY,
    PROTECTED,
    V4_REPORT,
    V4_TECHNICAL,
    B33,
    "resolve_workspace/modules/final_occlusion_composition_v1.py",
    "resolve_workspace/modules/final_occlusion_composition_v4.py",
    "resolve_workspace/modules/step_3D_visual_instance_correction.py",
    "resolve_workspace/VC_Agent_Bridge.py",
)


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


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("vc_motion_fade_authority_builder", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def active_commands(root: Path) -> List[Path]:
    rows: List[Path] = []
    for state in ("pending", "running"):
        directory = root / ".agent" / "commands" / state
        if directory.is_dir():
            rows.extend(sorted(directory.glob("*.json")))
    return rows


def validate_accepted(v4: Mapping[str, Any], technical: Mapping[str, Any], b33: Mapping[str, Any]) -> None:
    if (
        v4.get("ok") is not True
        or v4.get("target_timeline_name") != SOURCE_TIMELINE
        or v4.get("final_textplus_count") != 114
        or v4.get("caption_mutation_count") != 0
        or v4.get("save_call_count") != 1
        or v4.get("persistent_readback_ok") is not True
        or v4.get("idempotency_ok") is not True
    ):
        raise ValueError("accepted_v4_report")
    checks = technical.get("checks") if isinstance(technical.get("checks"), Mapping) else {}
    if technical.get("ok") is not True or not checks or not all(value is True for value in checks.values()):
        raise ValueError("accepted_v4_technical")
    decision = b33.get("decision") if isinstance(b33.get("decision"), Mapping) else {}
    if b33.get("ok") is not True or decision.get("accepted_timeline_remains") != SOURCE_TIMELINE or decision.get("step_3B3_status") != "complete_no_mutation_required":
        raise ValueError("accepted_b33")


def publish(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file():
        raise ValueError("repository_root")
    active = active_commands(root)
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    if not (root / VF).is_file() or normalized_sha256(root / VF) != VF_HASH:
        raise ValueError("visual_fidelity_v2_hash")

    builder = load_module(root / AUTHORITY_BUILDER)
    authority = builder.build(root)
    write_json(root / AUTHORITY, authority)
    if authority.get("ok") is not True:
        raise ValueError("authority")
    summary = authority.get("summary") or {}
    if summary.get("unique_center_target_count") != 7 or summary.get("protected_opacity_target_count") != 17 or summary.get("total_source_detected_exit_count") != 4:
        raise ValueError("authority_summary")

    validate_accepted(load_json(root / V4_REPORT), load_json(root / V4_TECHNICAL), load_json(root / B33))
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
        "motion_fade": {
            "source_timeline_name": SOURCE_TIMELINE,
            "target_timeline_name": TARGET_TIMELINE,
            "expected_textplus_count": 114,
            "authority_path": AUTHORITY,
            "authority_raw_sha256": raw_sha256(root / AUTHORITY),
            "center_target_count": 7,
            "protected_opacity_target_count": 17,
            "repair_caption_opacity_authorized": False,
            "size_mutation_authorized": False,
            "style_mutation_authorized": False,
            "caption_recreation_authorized": False,
            "timing_track_mutation_authorized": False,
            "occlusion_mutation_authorized": False,
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
    write_json(report_dir / "motion_fade_command.json", command)
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
