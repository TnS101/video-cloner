#!/usr/bin/env python3
"""Publish one temporal occlusion correction command from the accepted baseline."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import struct
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping

TASK_ID = "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V2"
MODE = "FINAL_OCCLUSION_COMPOSITION_V2"
MODULE = "resolve_workspace/modules/final_occlusion_composition_v2.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
REJECTED_V1_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v1"
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v2"
EXPECTED_TEXTPLUS_COUNT = 114
OLD_MATTE_NAME = "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052"
OLD_MATTE_RANGE = [429, 434]
NEW_MATTE_NAME = "VC_OCCLUSION_RGBA_matte_span_0001_temporal_v2_sub_0052"
NEW_MATTE_RANGE = [426, 454]
NEW_MATTE_DURATION = 28
SOURCE_VIDEO = "input/DZsqH7auhjt.mp4"
SOURCE_VIDEO_SHA256 = "fd60f596fb09031d8fa41071691cbdc1884edb32fd79f436f6be1df1ca186635"
ASSET_DIR = "data/DZsqH7auhjt/analysis/foreground_rgba_assets/matte_span_0001_temporal_v2"
ASSET_MANIFEST = f"{ASSET_DIR}/manifest.json"
OLD_ASSET_DIR = "data/DZsqH7auhjt/analysis/foreground_rgba_assets/matte_span_0001"
PRIOR_REPORT = ".agent/reports/DZSQH7AUHJT_STEP_3E_POST_VISUAL_METRICS_POLISH_V1/20260811T064144161728Z_3450ef48bc7046bfb059bbe778a2682f/report.json"
PRIOR_PERSISTENT = ".agent/reports/DZSQH7AUHJT_STEP_3E_POST_VISUAL_METRICS_POLISH_V1/20260811T064144161728Z_3450ef48bc7046bfb059bbe778a2682f/persistent_readback.json"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
SOURCE_PATHS = (
    MODULE,
    "resolve_workspace/modules/final_occlusion_composition_v1.py",
    "resolve_workspace/resolve_apply_video_cloner_metadata.py",
    "resolve_workspace/modules/step_3D_glyph_mask_render_probe.py",
    "resolve_workspace/modules/step_3E_post_visual_metrics_polish_v1.py",
    "resolve_workspace/modules/step_3E_confirmed74_isolated_repair_rollout_v1.py",
    "resolve_workspace/modules/step_3E_remaining100_full_rollout_v1.py",
    "resolve_workspace/modules/step_3D_visual_first_full_rollout_baseline.py",
    "resolve_workspace/modules/step_3D_visual_first_resolve_pilot.py",
    "resolve_workspace/modules/step_3D_full_lifecycle_textplus_rollout.py",
    "resolve_workspace/modules/step_3D_existing_textplus_clone_probe.py",
    "resolve_workspace/VC_Agent_Bridge.py",
    PRIOR_REPORT,
    PRIOR_PERSISTENT,
)
ASSET_FILES = tuple([ASSET_MANIFEST] + [f"{ASSET_DIR}/rgba_{frame:06d}.png" for frame in range(*NEW_MATTE_RANGE)])


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


def png_rgba_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:33]
    if len(header) < 33 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"png_header:{path}")
    width, height = struct.unpack(">II", header[16:24])
    bit_depth = header[24]
    color_type = header[25]
    if bit_depth != 8 or color_type != 6:
        raise ValueError(f"png_rgba8:{path}:{bit_depth}:{color_type}")
    return int(width), int(height)


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


def validate_temporal_asset(root: Path) -> Dict[str, Any]:
    manifest = load_json(root / ASSET_MANIFEST)
    if (
        manifest.get("task_id") != TASK_ID
        or manifest.get("item_name") != NEW_MATTE_NAME
        or manifest.get("cue_id") != "sub_0052"
        or manifest.get("timeline_range_half_open") != NEW_MATTE_RANGE
        or manifest.get("duration_frames") != NEW_MATTE_DURATION
        or manifest.get("source_video_sha256") != SOURCE_VIDEO_SHA256
    ):
        raise ValueError("temporal_asset_contract")
    frames = manifest.get("frames") if isinstance(manifest.get("frames"), list) else []
    if len(frames) != NEW_MATTE_DURATION or [row.get("timeline_frame") for row in frames] != list(range(*NEW_MATTE_RANGE)):
        raise ValueError("temporal_asset_frames")
    for row in frames:
        frame = int(row.get("timeline_frame") or -1)
        expected_source = round(frame * 30.0 / 24.0)
        if row.get("source_video_frame") != expected_source:
            raise ValueError(f"temporal_asset_source_mapping:{frame}")
        rgba = root / ASSET_DIR / f"rgba_{frame:06d}.png"
        if not rgba.is_file() or row.get("rgba_sha256") != raw_sha256(rgba) or row.get("rgba_size") != rgba.stat().st_size:
            raise ValueError(f"temporal_asset_rgba_contract:{frame}")
        if png_rgba_dimensions(rgba) != (1080, 1920):
            raise ValueError(f"temporal_asset_rgba_dimensions:{frame}")
    anchors = [row for row in frames if row.get("approved_anchor_reused") is True]
    if [row.get("timeline_frame") for row in anchors] != [429, 430, 431, 432, 433]:
        raise ValueError("temporal_asset_anchors")
    sentinels = list(((manifest.get("validation_contract") or {}).get("sentinel_frames") or []))
    if sentinels != [434, 438, 443, 448, 452, 453] or any(429 <= int(frame) < 434 for frame in sentinels):
        raise ValueError("temporal_asset_pixel_sentinels")
    for frame in range(429, 434):
        new_path = root / ASSET_DIR / f"rgba_{frame:06d}.png"
        old_path = root / OLD_ASSET_DIR / f"rgba_{frame:06d}.png"
        if not old_path.is_file() or raw_sha256(new_path) != raw_sha256(old_path):
            raise ValueError(f"approved_anchor_bytes:rgba:{frame}")
    for relative in ASSET_FILES:
        path = root / relative
        if not path.is_file() or path.stat().st_size <= 0:
            raise ValueError(f"temporal_asset_missing:{relative}")
    return {
        "asset_id": manifest.get("asset_id"),
        "timeline_range": NEW_MATTE_RANGE,
        "duration_frames": NEW_MATTE_DURATION,
        "approved_anchor_frames": [429, 430, 431, 432, 433],
        "asset_file_count": len(ASSET_FILES),
        "ok": True,
    }


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
    asset = validate_temporal_asset(root)

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
            "rejected_v1_timeline_name": REJECTED_V1_TIMELINE_NAME,
            "target_timeline_name": TARGET_TIMELINE_NAME,
            "old_matte_name": OLD_MATTE_NAME,
            "old_matte_range": OLD_MATTE_RANGE,
            "new_matte_name": NEW_MATTE_NAME,
            "new_matte_range": NEW_MATTE_RANGE,
            "expected_textplus_count": EXPECTED_TEXTPLUS_COUNT,
            "asset_contract": asset,
            "asset_hashes": {relative: raw_sha256(root / relative) for relative in ASSET_FILES},
            "source_video_sha256": SOURCE_VIDEO_SHA256,
            "caption_mutation_authorized": False,
            "non_occlusion_timeline_mutation_authorized": False,
            "pixel_render_evidence_required": True,
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
    write_json(report_dir / "occlusion_v2_command.json", command)
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
