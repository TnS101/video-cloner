#!/usr/bin/env python3
"""Publish one native-indexed sparse occlusion V4 command."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping

TASK_ID = "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V4"
MODE = "FINAL_OCCLUSION_COMPOSITION_V4"
MODULE = "resolve_workspace/modules/final_occlusion_composition_v4.py"
PIXEL_VALIDATOR = "scripts/analysis/validate_final_occlusion_pixel_restore_v4.py"
V3_HELPER = "scripts/analysis/build_final_occlusion_pixel_restore_v3.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
REJECTED_V1_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v1"
REJECTED_V2_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v2"
REJECTED_V3_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v3"
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v4"
EXPECTED_TEXTPLUS_COUNT = 114
TARGET_CAPTION_NAME = "VC_TEXTPLUS_0052_sub_052"
TARGET_RANGE = [426, 454]
OLD_MATTE_NAME = "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052"
NEW_MATTE_NAME = "VC_OCCLUSION_PIXEL_RESTORE_matte_span_0001_v4_sub_0052"
SOURCE_VIDEO = "input/DZsqH7auhjt.mp4"
SOURCE_VIDEO_SHA256 = "fd60f596fb09031d8fa41071691cbdc1884edb32fd79f436f6be1df1ca186635"
ANCHOR_DIR = "data/DZsqH7auhjt/analysis/foreground_matte_spans/matte_span_0001"
ANCHOR_HASHES = {
    f"{ANCHOR_DIR}/mask_000429.png": "fbea2275e7f1edb16e1e3c2130c587a5948968e1af847d7abb36d41a3cf9a971",
    f"{ANCHOR_DIR}/mask_000430.png": "72f4f8cd0e7ecae13c8d28f3d1e44a77c890a730f591668430e0c613d84287b9",
    f"{ANCHOR_DIR}/mask_000431.png": "b1d5a8e481d2370355d82dc2d8e9ad7bb9bf0b4e5e9e162e97561fafd15f3d03",
    f"{ANCHOR_DIR}/mask_000432.png": "8f07161e5e1d0f597f9268efa851f700452ebd0d89858aa40721f1ef96979883",
    f"{ANCHOR_DIR}/mask_000433.png": "5831a4d86ba3b4bc0fd50908f46a4d8ecadfb9f7d304ecaac2d921ecf53ea74f",
}
PRIOR_REPORT = ".agent/reports/DZSQH7AUHJT_STEP_3E_POST_VISUAL_METRICS_POLISH_V1/20260811T064144161728Z_3450ef48bc7046bfb059bbe778a2682f/report.json"
PRIOR_PERSISTENT = ".agent/reports/DZSQH7AUHJT_STEP_3E_POST_VISUAL_METRICS_POLISH_V1/20260811T064144161728Z_3450ef48bc7046bfb059bbe778a2682f/persistent_readback.json"
V3_RUN = ".agent/reports/DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V3/20260812T160055844261Z_f292f909ae7d40358098157428affd43"
V3_TECHNICAL = V3_RUN + "/technical_validation.json"
V3_PIXEL = V3_RUN + "/pixel_validation_v3.json"
V3_APPLICATION = V3_RUN + "/occlusion_v3_application.json"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
SOURCE_PATHS = (
    MODULE,
    PIXEL_VALIDATOR,
    V3_HELPER,
    "resolve_workspace/modules/final_occlusion_composition_v1.py",
    "resolve_workspace/modules/final_occlusion_composition_v2.py",
    "resolve_workspace/modules/final_occlusion_composition_v3.py",
    "resolve_workspace/resolve_apply_video_cloner_metadata.py",
    "resolve_workspace/modules/step_3D_glyph_mask_render_probe.py",
    "resolve_workspace/VC_Agent_Bridge.py",
    PRIOR_REPORT,
    PRIOR_PERSISTENT,
    V3_TECHNICAL,
    V3_PIXEL,
    V3_APPLICATION,
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run_id_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex


def normalized_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()


def raw_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def validate_v3_failure(technical: Mapping[str, Any], pixel: Mapping[str, Any], application: Mapping[str, Any]) -> Dict[str, Any]:
    checks = technical.get("checks") if isinstance(technical.get("checks"), Mapping) else {}
    first = application.get("first_application") if isinstance(application.get("first_application"), Mapping) else {}
    imported = first.get("import") if isinstance(first.get("import"), Mapping) else {}
    properties = imported.get("properties") if isinstance(imported.get("properties"), Mapping) else {}
    append = first.get("append") if isinstance(first.get("append"), Mapping) else {}
    source_range = append.get("source_range_used")
    native = [int(properties.get("Start") or -1), int(properties.get("End") or -1) + 1]
    ok = bool(
        technical.get("ok") is False
        and checks.get("pixel_authority") is False
        and pixel.get("ok") is False
        and pixel.get("sentinel_pass_count") == 0
        and source_range == [0, 28]
        and native == TARGET_RANGE
        and int(properties.get("Frames") or 0) == 28
    )
    if not ok:
        raise ValueError("v3_failure_contract")
    return {
        "v3_pixel_authority_failed": True,
        "v3_sentinel_pass_count": 0,
        "rejected_source_range": source_range,
        "media_pool_native_range": native,
        "root_cause": "image_sequence_appended_with_relative_0_28_instead_of_native_426_454",
        "ok": True,
    }


def validate_external_python() -> Dict[str, Any]:
    executable = str(Path(sys.executable).resolve())
    proc = subprocess.run(
        [executable, "-c", "import json,cv2,numpy; print(json.dumps({'cv2':cv2.__version__,'numpy':numpy.__version__}))"],
        text=True, capture_output=True, timeout=30, check=False,
    )
    if proc.returncode != 0:
        raise ValueError(f"external_python_cv2_numpy:{proc.stderr[-500:]}")
    versions = json.loads(proc.stdout.strip().splitlines()[-1])
    return {"executable": executable, "versions": versions, "ok": True}


def validate_anchors(root: Path) -> Dict[str, Any]:
    rows = []
    for relative, expected in ANCHOR_HASHES.items():
        path = root / relative
        actual = raw_sha256(path) if path.is_file() else ""
        matched = actual == expected
        rows.append({"path": relative, "expected": expected, "actual": actual, "matched": matched})
        if not matched:
            raise ValueError(f"anchor_hash:{relative}")
    return {"rows": rows, "ok": True}


def publish(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file():
        raise ValueError("repository_root")
    active = active_commands(root)
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    for relative in SOURCE_PATHS:
        if not (root / relative).is_file():
            raise ValueError(f"source_missing:{relative}")

    video = root / SOURCE_VIDEO
    if not video.is_file() or raw_sha256(video) != SOURCE_VIDEO_SHA256:
        raise ValueError("source_video_hash")
    validate_prior(load_json(root / PRIOR_REPORT), load_json(root / PRIOR_PERSISTENT))
    v3_failure = validate_v3_failure(load_json(root / V3_TECHNICAL), load_json(root / V3_PIXEL), load_json(root / V3_APPLICATION))
    anchors = validate_anchors(root)
    external = validate_external_python()

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
            "rejected_timelines": [REJECTED_V1_TIMELINE_NAME, REJECTED_V2_TIMELINE_NAME, REJECTED_V3_TIMELINE_NAME],
            "target_timeline_name": TARGET_TIMELINE_NAME,
            "target_caption_name": TARGET_CAPTION_NAME,
            "target_range": TARGET_RANGE,
            "old_matte_name": OLD_MATTE_NAME,
            "new_matte_name": NEW_MATTE_NAME,
            "expected_textplus_count": EXPECTED_TEXTPLUS_COUNT,
            "source_video_sha256": SOURCE_VIDEO_SHA256,
            "anchor_mask_hashes": dict(ANCHOR_HASHES),
            "external_python": external["executable"],
            "external_python_versions": external["versions"],
            "architecture": "sparse_resolve_pixel_restore_native_sequence_indices",
            "rgb_authority": "resolve_render_with_target_come_disabled",
            "person_authority": "clean_humanseg_anchors_plus_global_affine_only",
            "image_sequence_source_range": TARGET_RANGE,
            "rejected_v3_source_range": [0, 28],
            "pre_save_pixel_gate_required": True,
            "forbidden": [
                "grabcut",
                "dense_optical_flow_mask_growth",
                "raw_source_rgb_overlay",
                "relative_zero_image_sequence_trim",
                "rejected_v1_v2_v3_source",
                "accepted_caption_mutation",
            ],
            "caption_mutation_authorized": False,
            "temporary_duplicate_caption_toggle_authorized": TARGET_CAPTION_NAME,
            "persistent_non_occlusion_mutation_authorized": False,
            "one_save_required": True,
            "one_resolve_invocation_required": True,
            "persistent_readback_required": True,
            "idempotency_required": True,
            "rendered_pixel_validation_required": True,
            "visual_approval_required": True,
            "v3_failure_evidence": v3_failure,
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
    write_json(report_dir / "occlusion_v4_command.json", command)
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
