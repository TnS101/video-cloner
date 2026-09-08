#!/usr/bin/env python3
"""Publish exactly one final occlusion composition command."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping

TASK_ID = "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V1"
MODE = "FINAL_OCCLUSION_COMPOSITION"
MODULE = "resolve_workspace/modules/final_occlusion_composition_v1.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v1"
EXPECTED_TEXTPLUS_COUNT = 114
MATTE_NAME = "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052"
MATTE_RANGE = [429, 434]
FOREGROUND_CONTRACT = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_foreground_assets.json"
FOREGROUND_VALIDATION = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_foreground_assets_validation.json"
PRIOR_REPORT = ".agent/reports/DZSQH7AUHJT_STEP_3E_POST_VISUAL_METRICS_POLISH_V1/20260811T064144161728Z_3450ef48bc7046bfb059bbe778a2682f/report.json"
PRIOR_PERSISTENT = ".agent/reports/DZSQH7AUHJT_STEP_3E_POST_VISUAL_METRICS_POLISH_V1/20260811T064144161728Z_3450ef48bc7046bfb059bbe778a2682f/persistent_readback.json"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
ASSET_DIR = "data/DZsqH7auhjt/analysis/foreground_rgba_assets/matte_span_0001"
ASSET_FILES = (
    f"{ASSET_DIR}/manifest.json",
    f"{ASSET_DIR}/rgba_000429.png",
    f"{ASSET_DIR}/rgba_000430.png",
    f"{ASSET_DIR}/rgba_000431.png",
    f"{ASSET_DIR}/rgba_000432.png",
    f"{ASSET_DIR}/rgba_000433.png",
)
SOURCE_PATHS = (
    MODULE,
    FOREGROUND_CONTRACT,
    FOREGROUND_VALIDATION,
    PRIOR_REPORT,
    PRIOR_PERSISTENT,
    "resolve_workspace/modules/step_3E_post_visual_metrics_polish_v1.py",
    "resolve_workspace/modules/step_3E_confirmed74_isolated_repair_rollout_v1.py",
    "resolve_workspace/modules/step_3E_remaining100_full_rollout_v1.py",
    "resolve_workspace/modules/step_3D_visual_first_full_rollout_baseline.py",
    "resolve_workspace/modules/step_3D_visual_first_resolve_pilot.py",
    "resolve_workspace/modules/step_3D_full_lifecycle_textplus_rollout.py",
    "resolve_workspace/modules/step_3D_existing_textplus_clone_probe.py",
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


def active_commands(root: Path) -> List[Path]:
    rows: List[Path] = []
    for state in ("pending", "running"):
        directory = root / ".agent" / "commands" / state
        if directory.is_dir():
            rows.extend(sorted(directory.glob("*.json")))
    return rows


def validate_foreground_contract(contract: Mapping[str, Any], validation: Mapping[str, Any]) -> Dict[str, Any]:
    if contract.get("ok") is not True or validation.get("ok") is not True:
        raise ValueError("foreground_contract")
    summary = contract.get("summary") if isinstance(contract.get("summary"), Mapping) else {}
    if summary.get("complete_asset_span_count") != 1 or summary.get("rgba_frames_written") != 5:
        raise ValueError("foreground_summary")
    spans = contract.get("asset_spans") if isinstance(contract.get("asset_spans"), list) else []
    if len(spans) != 1 or not isinstance(spans[0], Mapping):
        raise ValueError("foreground_span")
    span = spans[0]
    if (
        span.get("span_id") != "matte_span_0001"
        or span.get("complete") is not True
        or [span.get("timeline_frame_start"), span.get("timeline_frame_end_exclusive")] != MATTE_RANGE
        or span.get("duration_frames") != 5
        or span.get("affected_cue_ids") != ["sub_0052"]
    ):
        raise ValueError("foreground_span_geometry")
    rgba = span.get("rgba_asset") if isinstance(span.get("rgba_asset"), Mapping) else {}
    if rgba.get("complete") is not True or rgba.get("frame_count_written") != 5 or rgba.get("width") != 1080 or rgba.get("height") != 1920:
        raise ValueError("foreground_rgba")
    if validation.get("rgba_files_readable") != 5 or validation.get("transparent_rgba_files") != 5 or validation.get("nonempty_foreground_rgba_files") != 5:
        raise ValueError("foreground_validation")
    return {"span_id": "matte_span_0001", "timeline_range": MATTE_RANGE, "cue_id": "sub_0052", "ok": True}


def validate_prior(report: Mapping[str, Any], persistent: Mapping[str, Any]) -> None:
    if (
        report.get("ok") is not True
        or report.get("target_timeline_name") != SOURCE_TIMELINE_NAME
        or report.get("final_textplus_count") != EXPECTED_TEXTPLUS_COUNT
        or report.get("save_call_count") != 1
        or report.get("position_updates") != 0
        or report.get("opacity_updates") != 0
        or report.get("source_timeline_unchanged") is not True
    ):
        raise ValueError("prior_report")
    checks = persistent.get("checks")
    if persistent.get("ok") is not True or not isinstance(checks, Mapping) or not checks or not all(value is True for value in checks.values()):
        raise ValueError("prior_persistent")
    if persistent.get("expected_physical_textplus_count") != EXPECTED_TEXTPLUS_COUNT:
        raise ValueError("prior_persistent_count")


def publish(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file():
        raise ValueError("repository_root")
    active = active_commands(root)
    if active:
        raise ValueError(f"active_command:{active[0].name}")

    for relative in (*SOURCE_PATHS, *ASSET_FILES):
        if not (root / relative).is_file():
            raise ValueError(f"source_missing:{relative}")

    contract = load_json(root / FOREGROUND_CONTRACT)
    validation = load_json(root / FOREGROUND_VALIDATION)
    approved = validate_foreground_contract(contract, validation)
    validate_prior(load_json(root / PRIOR_REPORT), load_json(root / PRIOR_PERSISTENT))

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
        "source_contract": {
            "version": 1,
            "algorithm": SOURCE_HASH_ALGORITHM,
            "hashes": {relative: normalized_sha256(root / relative) for relative in SOURCE_PATHS},
        },
        "occlusion": {
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "target_timeline_name": TARGET_TIMELINE_NAME,
            "matte_name": MATTE_NAME,
            "timeline_range": MATTE_RANGE,
            "expected_textplus_count": EXPECTED_TEXTPLUS_COUNT,
            "approved_contract": approved,
            "asset_hashes": {relative: raw_sha256(root / relative) for relative in ASSET_FILES},
            "caption_mutation_authorized": False,
            "non_occlusion_timeline_mutation_authorized": False,
            "one_save_required": True,
            "one_resolve_invocation_required": True,
            "persistent_readback_required": True,
            "idempotency_required": True,
            "visual_approval_required": True,
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
        "manual_action_count": 1,
    }
    write_json(report_dir / "publication_receipt.json", receipt)
    write_json(report_dir / "occlusion_command.json", command)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        result = publish(args.root)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
