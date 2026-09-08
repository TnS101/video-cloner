"""Temporal correction for the accepted caption foreground occlusion.

The V1 runtime proved safe track placement but the human review showed that the
approved five-frame foreground asset ended while the accepted COME Text+ item
was still visible.  V2 keeps the same accepted 114-Text+ source timeline,
duplicates it, replaces only the old five-frame matte in the duplicate with a
source-backed 28-frame RGBA sequence, renders source/target review frames in
the same Resolve invocation, and preserves every caption property bit-for-bit.

The visually rejected V1 target is evidence only and is never used as source.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
import time
import struct
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Mapping, Sequence

TASK_ID = "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V2"
MODE = "FINAL_OCCLUSION_COMPOSITION_V2"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/final_occlusion_composition_v2.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
REJECTED_V1_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v1"
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v2"
EXPECTED_TEXTPLUS_COUNT = 114
OLD_MATTE_NAME = "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052"
OLD_MATTE_RANGE = (429, 434)
NEW_MATTE_NAME = "VC_OCCLUSION_RGBA_matte_span_0001_temporal_v2_sub_0052"
NEW_MATTE_RANGE = (426, 454)
NEW_MATTE_DURATION = 28
ASSET_DIR_RELATIVE = "data/DZsqH7auhjt/analysis/foreground_rgba_assets/matte_span_0001_temporal_v2"
ASSET_MANIFEST_RELATIVE = ASSET_DIR_RELATIVE + "/manifest.json"
RENDER_FRAME_IN = 426
RENDER_FRAME_OUT = 453
RENDER_FRAME_COUNT = 28
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
SOURCE_VIDEO_RELATIVE = "input/DZsqH7auhjt.mp4"
SOURCE_VIDEO_SHA256 = "fd60f596fb09031d8fa41071691cbdc1884edb32fd79f436f6be1df1ca186635"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
V1 = _load("vc_final_occlusion_v1_for_v2", HERE / "final_occlusion_composition_v1.py")
LEGACY = _load("vc_metadata_for_final_occlusion_v2", HERE.parent / "resolve_apply_video_cloner_metadata.py")
GLYPH = _load("vc_glyph_render_for_final_occlusion_v2", HERE / "step_3D_glyph_mask_render_probe.py")
base = V1.base
full = V1.full

OCCLUSION_NAMES = {OLD_MATTE_NAME, NEW_MATTE_NAME}
STABLE_INVENTORY_FIELDS = V1.STABLE_INVENTORY_FIELDS


def _normalized(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        return str(value) if not math.isfinite(value) else round(value, 9)
    if isinstance(value, Mapping):
        return {str(k): _normalized(v) for k, v in sorted(value.items(), key=lambda row: str(row[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalized(v) for v in value]
    return _normalized(base.json_safe(value))


def stable_inventory_without_occlusion(timeline: Any) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for track, item in base.all_video_items(timeline):
        if base.item_name(item) in OCCLUSION_NAMES:
            continue
        summary = base.item_summary(int(track), item)
        rows.append(tuple(summary.get(field) for field in STABLE_INVENTORY_FIELDS))
    return sorted(rows, key=lambda row: tuple("" if value is None else str(value) for value in row))


def item_inventory(timeline: Any, name: str) -> list[Dict[str, Any]]:
    rows = [
        base.item_summary(int(track), item)
        for track, item in base.all_video_items(timeline)
        if base.item_name(item) == name
    ]
    return sorted(rows, key=lambda row: (int(row.get("track_index") or 0), int(row.get("start") or 0)))


def verify_source_old_matte(timeline: Any) -> Dict[str, Any]:
    rows = item_inventory(timeline, OLD_MATTE_NAME)
    new_rows = item_inventory(timeline, NEW_MATTE_NAME)
    ok = bool(
        len(rows) == 1
        and not new_rows
        and int(rows[0].get("start") or -1) == OLD_MATTE_RANGE[0]
        and int(rows[0].get("end") or -1) == OLD_MATTE_RANGE[1]
        and int(rows[0].get("duration") or -1) == OLD_MATTE_RANGE[1] - OLD_MATTE_RANGE[0]
        and str(rows[0].get("media_pool_item_name") or "") == OLD_MATTE_NAME
    )
    return {"old_rows": rows, "new_rows": new_rows, "ok": ok}


def verify_extended_occlusion(timeline: Any) -> Dict[str, Any]:
    old_rows = item_inventory(timeline, OLD_MATTE_NAME)
    rows = item_inventory(timeline, NEW_MATTE_NAME)
    max_caption = V1.caption_track_max(timeline)
    ok = bool(
        not old_rows
        and len(rows) == 1
        and int(rows[0].get("track_index") or 0) > max_caption
        and int(rows[0].get("start") or -1) == NEW_MATTE_RANGE[0]
        and int(rows[0].get("end") or -1) == NEW_MATTE_RANGE[1]
        and int(rows[0].get("duration") or -1) == NEW_MATTE_DURATION
        and str(rows[0].get("media_pool_item_name") or "") == NEW_MATTE_NAME
    )
    return {
        "old_rows": old_rows,
        "rows": rows,
        "max_caption_track": max_caption,
        "required_layer_order": "foreground_rgba_temporal_v2_above_all_textplus",
        "ok": ok,
    }


def _png_rgba_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:33]
    if len(header) < 33 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise RuntimeError(f"png_header:{path}")
    width, height = struct.unpack(">II", header[16:24])
    if header[24] != 8 or header[25] != 6:
        raise RuntimeError(f"png_rgba8:{path}:{header[24]}:{header[25]}")
    return int(width), int(height)


def load_asset_manifest(root: Path) -> Dict[str, Any]:
    value = json.loads((root / ASSET_MANIFEST_RELATIVE).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("asset_manifest_object")
    return value


def validate_asset_manifest(root: Path, command: Mapping[str, Any]) -> Dict[str, Any]:
    manifest = load_asset_manifest(root)
    if (
        manifest.get("task_id") != TASK_ID
        or manifest.get("item_name") != NEW_MATTE_NAME
        or manifest.get("timeline_range_half_open") != list(NEW_MATTE_RANGE)
        or manifest.get("duration_frames") != NEW_MATTE_DURATION
        or manifest.get("cue_id") != "sub_0052"
    ):
        raise RuntimeError("asset_manifest_contract")
    rows = manifest.get("frames") if isinstance(manifest.get("frames"), list) else []
    if len(rows) != NEW_MATTE_DURATION or [row.get("timeline_frame") for row in rows] != list(range(*NEW_MATTE_RANGE)):
        raise RuntimeError("asset_manifest_frames")
    hashes = ((command.get("occlusion") or {}).get("asset_hashes") if isinstance(command.get("occlusion"), Mapping) else None)
    if not isinstance(hashes, Mapping) or len(hashes) != 1 + NEW_MATTE_DURATION:
        raise RuntimeError("asset_hashes")
    verified = []
    for relative, expected in sorted(hashes.items()):
        path = root / str(relative)
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"asset_missing:{relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.suffix.lower() == ".png" and _png_rgba_dimensions(path) != (1080, 1920):
            raise RuntimeError(f"asset_dimensions:{relative}")
        matched = actual == str(expected)
        verified.append({"path": str(relative), "expected": str(expected), "actual": actual, "matched": matched, "size": path.stat().st_size})
        if not matched:
            raise RuntimeError(f"asset_hash:{relative}")
    for row in rows:
        frame = int(row.get("timeline_frame") or -1)
        expected_source = round(frame * 30.0 / 24.0)
        if row.get("source_video_frame") != expected_source:
            raise RuntimeError(f"asset_source_mapping:{frame}")
        relative = f"{ASSET_DIR_RELATIVE}/rgba_{frame:06d}.png"
        if row.get("rgba_sha256") != hashes.get(relative):
            raise RuntimeError(f"asset_manifest_rgba_hash:{frame}")
    anchors = [row for row in rows if row.get("approved_anchor_reused") is True]
    if [row.get("timeline_frame") for row in anchors] != [429, 430, 431, 432, 433]:
        raise RuntimeError("approved_anchor_set")
    sentinels = list(((manifest.get("validation_contract") or {}).get("sentinel_frames") or []))
    if sentinels != [434, 438, 443, 448, 452, 453] or any(429 <= int(frame) < 434 for frame in sentinels):
        raise RuntimeError("asset_pixel_sentinels")
    return {"manifest": manifest, "rows": verified, "verified_count": len(verified), "ok": True}


def _asset_span(root: Path) -> Dict[str, Any]:
    return {
        "span_id": "matte_span_0001_temporal_v2",
        "item_name": NEW_MATTE_NAME,
        "timeline_frame_start": NEW_MATTE_RANGE[0],
        "timeline_frame_end_exclusive": NEW_MATTE_RANGE[1],
        "duration_frames": NEW_MATTE_DURATION,
        "rgba_pattern": str((root / ASSET_DIR_RELATIVE / "rgba_%06d.png").resolve()),
        "first_rgba_file": str((root / ASSET_DIR_RELATIVE / f"rgba_{NEW_MATTE_RANGE[0]:06d}.png").resolve()),
        "canonical_cue_ids": ["sub_0052"],
    }


def _legacy_args() -> SimpleNamespace:
    return SimpleNamespace(
        caption_occlusion_reuse_media_pool_items=True,
        caption_occlusion_set_straight_alpha=True,
        caption_occlusion_alpha_mode="Straight",
        caption_occlusion_verify_settle_timeout_sec=2.0,
        caption_occlusion_verify_poll_interval_sec=0.10,
    )


def ensure_extended_occlusion(project: Any, timeline: Any, root: Path) -> Dict[str, Any]:
    before = verify_extended_occlusion(timeline)
    if before["ok"]:
        return {"ok": True, "mutated": False, "idempotent_noop": True, "before": before, "after": before}

    source_preimage = verify_source_old_matte(timeline)
    if not source_preimage["ok"]:
        return {"ok": False, "mutated": False, "error": "old_matte_preimage", "before": source_preimage}

    old_track, old_item = next(
        (int(track), item)
        for track, item in base.all_video_items(timeline)
        if base.item_name(item) == OLD_MATTE_NAME
    )
    target_track = V1.caption_track_max(timeline) + 1
    track_setup = base.ensure_video_tracks(timeline, target_track)
    if not track_setup.get("ok"):
        return {"ok": False, "mutated": False, "error": "track_setup", "track_setup": track_setup}

    span = _asset_span(root)
    args = _legacy_args()
    imported = LEGACY._import_rgba_sequence_media_pool(project, span, args, 24.0)
    if not imported.get("ok") or imported.get("item") is None:
        return {"ok": False, "mutated": False, "error": "rgba_import", "import": base.json_safe({k: v for k, v in imported.items() if k != "item"})}
    new_media_item = imported["item"]

    deletion = base.delete_items(timeline, [old_item])
    time.sleep(0.15)
    if not deletion.get("ok") or item_inventory(timeline, OLD_MATTE_NAME):
        return {
            "ok": False,
            "mutated": True,
            "error": "old_matte_delete",
            "imported_media_item": new_media_item,
            "imported_new": bool(imported.get("imported")),
            "deletion": deletion,
        }

    append = LEGACY._append_rgba_sequence_item(project, timeline, new_media_item, span, target_track, args)
    verification = verify_extended_occlusion(timeline)
    return {
        "ok": bool(append.get("ok") and verification.get("ok")),
        "mutated": True,
        "idempotent_noop": False,
        "source_track": old_track,
        "target_track": target_track,
        "track_setup": track_setup,
        "import": base.json_safe({k: v for k, v in imported.items() if k != "item"}),
        "imported_media_item": new_media_item,
        "imported_new": bool(imported.get("imported")),
        "deletion": deletion,
        "append": base.json_safe({k: v for k, v in append.items() if k != "item"}),
        "verification": verification,
    }


def _render_selection(project: Any) -> Dict[str, Any]:
    formats = base.safe_value(project, "GetRenderFormats", default={})
    if not isinstance(formats, Mapping) or not formats:
        raise RuntimeError("render_formats")
    codecs: Dict[str, Mapping[str, Any]] = {}
    for render_format in formats:
        value = base.safe_value(project, "GetRenderCodecs", str(render_format), default={})
        codecs[str(render_format)] = value if isinstance(value, Mapping) else {}
    selected = GLYPH.select_lossless_render_format(formats, codecs)
    if not selected.get("ok") or not isinstance(selected.get("selected"), Mapping):
        raise RuntimeError("lossless_render_format")
    row = dict(selected["selected"])
    if str(row.get("extension") or "").lower() != "png":
        raise RuntimeError("png_render_unavailable")
    return {"formats": base.json_safe(formats), "codecs": base.json_safe(codecs), "selection": row}


def _status_text(status: Any) -> str:
    return GLYPH.status_text(status)


def _render_sequence(project: Any, timeline: Any, output_dir: Path, custom_name: str, selection: Mapping[str, Any], dimensions: Mapping[str, Any]) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=False)
    calls = []
    job_id = ""
    try:
        value, call = base.direct_call(project, "SetCurrentTimeline", timeline); calls.append(call)
        if not value:
            raise RuntimeError("set_current_timeline")
        value, call = base.direct_call(project, "SetCurrentRenderFormatAndCodec", str(selection["format"]), str(selection["codec"])); calls.append(call)
        if not value:
            raise RuntimeError("set_render_format_codec")
        value, call = base.direct_call(project, "SetCurrentRenderMode", 1); calls.append(call)
        if not value:
            raise RuntimeError("set_render_mode")
        settings = {
            "SelectAllFrames": False,
            "MarkIn": RENDER_FRAME_IN,
            "MarkOut": RENDER_FRAME_OUT,
            "TargetDir": str(output_dir),
            "CustomName": custom_name,
            "UniqueFilenameStyle": 1,
            "ExportVideo": True,
            "ExportAudio": False,
            "FormatWidth": int(dimensions["width"]),
            "FormatHeight": int(dimensions["height"]),
            "FrameRate": float(dimensions["frame_rate"]),
            "PixelAspectRatio": "square",
            "ReplaceExistingFilesInPlace": True,
        }
        value, call = base.direct_call(project, "SetRenderSettings", settings); calls.append(call)
        if not value:
            raise RuntimeError("set_render_settings")
        raw_job_id, call = base.direct_call(project, "AddRenderJob"); calls.append(call)
        job_id = str(raw_job_id or "")
        if not job_id:
            raise RuntimeError("add_render_job")
        value, call = base.direct_call(project, "StartRendering", job_id); calls.append(call)
        if not value:
            raise RuntimeError("start_rendering")
        deadline = time.monotonic() + 900.0
        statuses = []
        while time.monotonic() < deadline:
            raw = base.safe_value(project, "GetRenderJobStatus", job_id, default={})
            rendering = bool(base.safe_value(project, "IsRenderingInProgress", default=False))
            text = _status_text(raw)
            if not statuses or statuses[-1]["text"] != text or statuses[-1]["rendering"] != rendering:
                statuses.append({"text": text, "rendering": rendering, "status": base.json_safe(raw), "observed_at": base.utc_now()})
            if any(token in text for token in ("fail", "cancel", "error")):
                raise RuntimeError(f"render_failed:{text}")
            if text in {"complete", "completed", "success", "succeeded"} and not rendering:
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("render_timeout")
        files = sorted(path for path in output_dir.glob("*.png") if path.is_file())
        if len(files) != RENDER_FRAME_COUNT or any(path.stat().st_size <= 0 for path in files):
            raise RuntimeError(f"render_file_count:{len(files)}")
        return {
            "ok": True,
            "timeline_name": base.timeline_name(timeline),
            "timeline_unique_id": base.timeline_unique_id(timeline),
            "output_dir": str(output_dir),
            "settings": settings,
            "selection": dict(selection),
            "job_id": job_id,
            "statuses": statuses,
            "files": [str(path) for path in files],
            "file_hashes": {path.name: base.raw_sha256(path) for path in files},
            "calls": calls,
        }
    except BaseException as exc:
        if bool(base.safe_value(project, "IsRenderingInProgress", default=False)):
            _, call = base.direct_call(project, "StopRendering"); calls.append(call)
        return {"ok": False, "error": base.compact_exception(exc), "traceback": traceback.format_exc(), "job_id": job_id, "calls": calls}
    finally:
        if job_id:
            base.direct_call(project, "DeleteRenderJob", job_id)


def render_pixel_evidence(resolve: Any, project: Any, source: Any, target: Any, report_dir: Path) -> Dict[str, Any]:
    original_page = str(base.safe_value(resolve, "GetCurrentPage", default="") or "")
    original_timeline = base.safe_value(project, "GetCurrentTimeline", default=None)
    current_render = base.safe_value(project, "GetCurrentRenderFormatAndCodec", default={})
    original_format = current_render.get("format") if isinstance(current_render, Mapping) else None
    original_codec = current_render.get("codec") if isinstance(current_render, Mapping) else None
    original_mode = base.as_int(base.safe_value(project, "GetCurrentRenderMode", default=1), 1)
    selection = _render_selection(project)
    dimensions = GLYPH.timeline_dimensions(target, project)
    if int(dimensions.get("width") or 0) != 1080 or int(dimensions.get("height") or 0) != 1920 or abs(float(dimensions.get("frame_rate") or 0) - 24.0) > 0.001:
        raise RuntimeError(f"render_dimensions:{dimensions}")
    opened, open_call = base.direct_call(resolve, "OpenPage", "deliver")
    if not opened:
        raise RuntimeError("open_deliver")
    source_render = _render_sequence(project, source, report_dir / "render_source_baseline", "source_baseline", selection["selection"], dimensions)
    target_render = _render_sequence(project, target, report_dir / "render_target_occlusion_v2", "target_occlusion_v2", selection["selection"], dimensions)

    restore_calls = []
    restore_results = []
    if original_timeline is not None:
        value, call = base.direct_call(project, "SetCurrentTimeline", original_timeline); restore_calls.append(call); restore_results.append(bool(value))
    if original_format and original_codec:
        value, call = base.direct_call(project, "SetCurrentRenderFormatAndCodec", str(original_format), str(original_codec)); restore_calls.append(call); restore_results.append(bool(value))
    value, call = base.direct_call(project, "SetCurrentRenderMode", original_mode); restore_calls.append(call); restore_results.append(bool(value))
    value, call = base.direct_call(project, "SetRenderSettings", {"SelectAllFrames": True}); restore_calls.append(call); restore_results.append(bool(value))
    if original_page:
        value, call = base.direct_call(resolve, "OpenPage", original_page); restore_calls.append(call); restore_results.append(bool(value))

    restore_ok = bool(restore_results and all(restore_results))
    ok = bool(source_render.get("ok") and target_render.get("ok") and restore_ok)
    return {
        "ok": ok,
        "restore_ok": restore_ok,
        "frame_range_half_open": list(NEW_MATTE_RANGE),
        "frame_count": RENDER_FRAME_COUNT,
        "dimensions": dimensions,
        "render_capability": selection,
        "source": source_render,
        "target": target_render,
        "restore_calls": restore_calls,
        "original_page": original_page,
        "original_render_format": original_format,
        "original_render_codec": original_codec,
        "original_render_mode": original_mode,
    }


def cleanup_before_save(project_manager: Any, project: Any, media_pool: Any, source: Any, imported_media_item: Any, imported_new: bool) -> Dict[str, Any]:
    result: Dict[str, Any] = {"errors": [], "save_call_count": 0}
    try:
        target = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if source is not None:
            selected, call = base.direct_call(project, "SetCurrentTimeline", source); result["restore_source"] = call
            if not selected:
                result["errors"].append("restore_source")
        if target is not None:
            deleted, call = base.direct_call(media_pool, "DeleteTimelines", [target]); result["delete_target"] = call
            if not deleted:
                result["errors"].append("delete_target")
        if imported_new and imported_media_item is not None:
            deletion = LEGACY._delete_media_pool_items(project, [imported_media_item]); result["delete_imported_media"] = base.json_safe(deletion)
            if not deletion.get("ok"):
                result["errors"].append("delete_imported_media")
        save = base.save_project(project_manager); result["save"] = save; result["save_call_count"] = 1
        if not save.get("success"):
            result["errors"].append("save_cleanup")
    except BaseException as exc:
        result["errors"].append(base.compact_exception(exc)); result["traceback"] = traceback.format_exc()
    result["ok"] = not result["errors"]
    return result


def run(resolve: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    root = base.repository_root()
    command = context.get("command") if isinstance(context, dict) else None
    if not isinstance(command, dict):
        raise ValueError("command")
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    if command.get("task_id") != TASK_ID or command.get("mode") != MODE or not run_id:
        raise ValueError("command_identity")
    report_dir = base.relative_path(root, command.get("artifacts_dir")); report_dir.mkdir(parents=True, exist_ok=True)
    report: Dict[str, Any] = {
        "schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "mode": MODE, "ok": False,
        "source_timeline_name": SOURCE_TIMELINE_NAME, "rejected_v1_timeline_ignored": REJECTED_V1_TIMELINE_NAME,
        "target_timeline_name": TARGET_TIMELINE_NAME, "save_call_count": 0, "resolve_invocation_contract": 1,
        "caption_mutation_count": 0, "occlusion_mutation_count": 0, "final_textplus_count": 0,
        "source_timeline_unchanged": False, "caption_baseline_unchanged": False, "persistent_readback_ok": False,
        "idempotency_ok": False, "pixel_render_evidence_generated": False, "visual_approval_required": True,
        "further_rollout_authorized": False, "failures": [],
    }
    project_manager = project = media_pool = source = None
    imported_media_item = None
    imported_new = False
    target_created = False
    saved = False
    try:
        source_contract = base.verify_source_contract(root, command); base.write_json(report_dir / "source_contract_verification.json", source_contract)
        video_path = root / SOURCE_VIDEO_RELATIVE
        expected_video_hash = str(((command.get("occlusion") or {}).get("source_video_sha256") or ""))
        actual_video_hash = base.raw_sha256(video_path) if video_path.is_file() else ""
        source_video_verification = {
            "path": SOURCE_VIDEO_RELATIVE,
            "expected_sha256": SOURCE_VIDEO_SHA256,
            "command_sha256": expected_video_hash,
            "actual_sha256": actual_video_hash,
            "ok": bool(expected_video_hash == SOURCE_VIDEO_SHA256 == actual_video_hash),
        }
        base.write_json(report_dir / "source_video_verification.json", source_video_verification)
        if not source_video_verification["ok"]:
            raise RuntimeError("source_video_hash")
        assets = validate_asset_manifest(root, command); base.write_json(report_dir / "temporal_rgba_asset_verification.json", assets)
        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        if base.find_timeline(project, TARGET_TIMELINE_NAME) is not None:
            raise RuntimeError("target_exists")
        source_uid = base.timeline_unique_id(source)
        source_caption_before = V1.caption_snapshot(source)
        source_full_before = V1.stable_inventory(source)
        source_nonocc_before = stable_inventory_without_occlusion(source)
        source_matte = verify_source_old_matte(source)
        if not source_matte["ok"]:
            raise RuntimeError("source_old_matte")
        if full.track_two_item_names(source):
            raise RuntimeError("source_v2_not_empty")
        base.write_json(report_dir / "occlusion_v2_preflight.json", {
            "schema_version":1,"task_id":TASK_ID,"run_id":run_id,"resolve_calls":resolve_calls,
            "source_unique_id":source_uid,"source_caption_snapshot":source_caption_before,"source_matte":source_matte,
            "source_non_occlusion_inventory":source_nonocc_before,"expected_textplus_count":EXPECTED_TEXTPLUS_COUNT,"ok":True,
        })

        duplicate_value, duplicate_call = base.direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
        target = duplicate_value if duplicate_value is not None else base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target is None:
            raise RuntimeError("duplicate_timeline")
        target_created = True
        selected, select_call = base.direct_call(project, "SetCurrentTimeline", target)
        if not selected:
            raise RuntimeError("select_target")
        target_caption_duplicate = V1.caption_snapshot(target)
        if not V1.caption_snapshots_equal(source_caption_before, target_caption_duplicate):
            raise RuntimeError("duplicate_caption_regression")
        if stable_inventory_without_occlusion(target) != source_nonocc_before:
            raise RuntimeError("duplicate_non_occlusion_regression")

        first = ensure_extended_occlusion(project, target, root)
        imported_media_item = first.get("imported_media_item")
        imported_new = bool(first.get("imported_new"))
        target_caption_after_first = V1.caption_snapshot(target)
        first_caption_unchanged = V1.caption_snapshots_equal(target_caption_duplicate, target_caption_after_first)
        first_nonocc_unchanged = stable_inventory_without_occlusion(target) == source_nonocc_before
        if not first.get("ok") or not first.get("mutated") or not first_caption_unchanged or not first_nonocc_unchanged:
            raise RuntimeError("occlusion_v2_first_application")

        second = ensure_extended_occlusion(project, target, root)
        target_caption_after_second = V1.caption_snapshot(target)
        second_caption_unchanged = V1.caption_snapshots_equal(target_caption_after_first, target_caption_after_second)
        second_nonocc_unchanged = stable_inventory_without_occlusion(target) == source_nonocc_before
        if not second.get("ok") or second.get("mutated") or second.get("idempotent_noop") is not True or not second_caption_unchanged or not second_nonocc_unchanged:
            raise RuntimeError("occlusion_v2_idempotency")
        pre_save = verify_extended_occlusion(target)
        if not pre_save["ok"]:
            raise RuntimeError("occlusion_v2_pre_save")

        base.write_json(report_dir / "occlusion_v2_application.json", {
            "duplicate_call":duplicate_call,"select_call":select_call,"first_application":base.json_safe({k:v for k,v in first.items() if k!="imported_media_item"}),
            "second_application":base.json_safe({k:v for k,v in second.items() if k!="imported_media_item"}),
            "checks":{"duplicate_caption_baseline_exact":True,"duplicate_non_occlusion_inventory_exact":True,
                "first_caption_baseline_unchanged":first_caption_unchanged,"first_non_occlusion_inventory_unchanged":first_nonocc_unchanged,
                "second_is_idempotent_noop":second.get("idempotent_noop") is True and second.get("mutated") is False,
                "second_caption_baseline_unchanged":second_caption_unchanged,"second_non_occlusion_inventory_unchanged":second_nonocc_unchanged,
                "extended_occlusion_above_all_caption_tracks":pre_save["ok"]},
            "caption_snapshot_before":target_caption_duplicate,"caption_snapshot_after":target_caption_after_second,"occlusion":pre_save,"ok":True,
        })

        render_evidence = render_pixel_evidence(resolve, project, source, target, report_dir)
        base.write_json(report_dir / "pixel_render_evidence.json", render_evidence)
        if not render_evidence.get("ok"):
            raise RuntimeError("pixel_render_evidence")
        report["pixel_render_evidence_generated"] = True

        save = base.save_project(project_manager); report["save_call_count"] = 1; saved = True
        if not save.get("success"):
            raise RuntimeError("save")
        project_manager, project, media_pool, reacquire_calls = base.get_project(resolve)
        source_after = base.find_timeline(project, SOURCE_TIMELINE_NAME); target_after = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if source_after is None or target_after is None:
            raise RuntimeError("reacquire")
        source_caption_after = V1.caption_snapshot(source_after); target_caption_persistent = V1.caption_snapshot(target_after)
        target_occlusion = verify_extended_occlusion(target_after)
        checks = {
            "source_timeline_unique_id_unchanged":base.timeline_unique_id(source_after)==source_uid,
            "source_full_inventory_unchanged":V1.stable_inventory(source_after)==source_full_before,
            "source_caption_baseline_unchanged":V1.caption_snapshots_equal(source_caption_before,source_caption_after),
            "target_caption_baseline_unchanged":V1.caption_snapshots_equal(source_caption_before,target_caption_persistent),
            "target_non_occlusion_inventory_unchanged":stable_inventory_without_occlusion(target_after)==source_nonocc_before,
            "extended_occlusion_exact":target_occlusion["ok"],"physical_textplus_count":target_caption_persistent["count"]==EXPECTED_TEXTPLUS_COUNT,
            "v2_empty":not full.track_two_item_names(target_after),"one_save":report["save_call_count"]==1,
            "idempotency_proven_pre_save":second.get("idempotent_noop") is True and second.get("mutated") is False,
            "pixel_render_evidence_generated":report["pixel_render_evidence_generated"] is True,
        }
        persistent={"schema_version":1,"task_id":TASK_ID,"run_id":run_id,"reacquire_calls":reacquire_calls,"save":save,
            "source_caption_snapshot_before":source_caption_before,"source_caption_snapshot_after":source_caption_after,
            "target_caption_snapshot":target_caption_persistent,"occlusion":target_occlusion,"checks":checks,
            "visual_approval_required":True,"further_rollout_authorized":False,"ok":all(checks.values())}
        base.write_json(report_dir / "persistent_readback.json", persistent)
        if not persistent["ok"]:
            raise RuntimeError("persistent_readback")
        report.update({"ok":True,"occlusion_mutation_count":1,"final_textplus_count":EXPECTED_TEXTPLUS_COUNT,
            "source_timeline_unchanged":True,"caption_baseline_unchanged":True,"persistent_readback_ok":True,"idempotency_ok":True,
            "occlusion_target_track":int(target_occlusion["rows"][0]["track_index"]),"target_timeline_kept":True})
        return report
    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc)); report["traceback"] = traceback.format_exc()
        if target_created and not saved and project_manager is not None and project is not None and media_pool is not None:
            cleanup = cleanup_before_save(project_manager, project, media_pool, source, imported_media_item, imported_new)
            base.write_json(report_dir / "failure_cleanup.json", cleanup); report["save_call_count"] = int(cleanup.get("save_call_count") or 0); report["failure_cleanup_ok"] = cleanup.get("ok") is True
        elif saved:
            report["post_save_failure_target_retained"] = True; report["manual_delete_required_before_next_task"] = True
        return report
