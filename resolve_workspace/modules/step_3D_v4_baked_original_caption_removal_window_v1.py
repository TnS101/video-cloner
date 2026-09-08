"""Integrate one bounded baked-original caption removal window under Text+.

Architecture:
  accepted source timeline
    -> disposable duplicate, disable all editable Text+ + V4 foreground restore
    -> exact Resolve RGB8 base render [400,480)
    -> offline HumanSeg + temporal reconstruction builds sparse RGBA [426,455)
    -> fresh duplicate of accepted source
    -> append sparse restore on empty V2, below all Text+ and below V4 occlusion
    -> disposable validation duplicate disables Text+ + V4 occlusion only
    -> exact rendered pixel gate before the single SaveProject call

No accepted caption property, timing, track, motion/fade, size correction or V4
occlusion state may change.  This V1 proves only cues sub_051..sub_056; full-reel
rollout remains unauthorized until human visual approval.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

TASK_ID = "DZSQH7AUHJT_STEP_3D_V4_BAKED_ORIGINAL_CAPTION_REMOVAL_WINDOW_V1"
MODE = "STEP_3D_V4_BAKED_ORIGINAL_CAPTION_REMOVAL_WINDOW_V1"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3D_v4_baked_original_caption_removal_window_v1.py"
HELPER_RELATIVE_PATH = "scripts/analysis/build_step_3D_v4_baked_original_caption_removal_window_v1.py"
PIXEL_VALIDATOR_RELATIVE_PATH = "scripts/analysis/validate_step_3D_v4_baked_original_caption_removal_window_v1.py"
STYLE_RELATIVE_PATH = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_style.json"
LIFECYCLE_RELATIVE_PATH = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_lifecycle_authority_step_3D_calibrated.json"
TRACKS_RELATIVE_PATH = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_word_instance_tracks_step_3B_6B.json"
EXPECTED_TEXTPLUS_COUNT = 114
CONTEXT_RANGE = (400, 480)
CLEAN_RANGE = (426, 455)
TARGET_TRACK = 2
RESTORE_NAME = "VC_BAKED_CAPTION_PIXEL_RESTORE_window_051_056_v1"
TEMP_BASE_PREFIX = "VC_BAKED_REMOVE_BASE_"
TEMP_VALIDATE_PREFIX = "VC_BAKED_REMOVE_VALIDATE_"
STABLE_FIELDS = ("name", "track_index", "start", "end", "duration", "media_pool_item_name", "fusion_comp_count")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
SIZE = _load("vc_the_size_fix_for_baked_removal", HERE / "caption_the_size_pop_fix_v1.py")
V4 = SIZE.V4
V1 = SIZE.V1
base = SIZE.base
full = SIZE.full
LEGACY = V4.LEGACY
GLYPH = V4.GLYPH
SOURCE_TIMELINE_NAME = SIZE.TARGET_TIMELINE_NAME
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_baked_remove_window_v1"


def item_inventory(timeline: Any, name: str) -> list[Dict[str, Any]]:
    rows = [
        base.item_summary(int(track), item)
        for track, item in base.all_video_items(timeline)
        if base.item_name(item) == name
    ]
    return sorted(rows, key=lambda row: (int(row.get("track_index") or 0), int(row.get("start") or 0)))


def stable_inventory_without_restore(timeline: Any) -> list[tuple[Any, ...]]:
    rows = []
    for track, item in base.all_video_items(timeline):
        if base.item_name(item) == RESTORE_NAME:
            continue
        summary = base.item_summary(int(track), item)
        rows.append(tuple(summary.get(field) for field in STABLE_FIELDS))
    return sorted(rows, key=lambda row: tuple("" if value is None else str(value) for value in row))


def verify_restore(timeline: Any) -> Dict[str, Any]:
    rows = item_inventory(timeline, RESTORE_NAME)
    v2_names = list(full.track_two_item_names(timeline))
    ok = bool(
        len(rows) == 1
        and int(rows[0].get("track_index") or -1) == TARGET_TRACK
        and [rows[0].get("start"), rows[0].get("end")] == list(CLEAN_RANGE)
        and int(rows[0].get("duration") or -1) == CLEAN_RANGE[1] - CLEAN_RANGE[0]
        and v2_names == [RESTORE_NAME]
    )
    return {"rows": rows, "v2_names": v2_names, "ok": ok}


def _delete_timeline(media_pool: Any, timeline: Any) -> Dict[str, Any]:
    value, call = base.direct_call(media_pool, "DeleteTimelines", [timeline])
    return {"ok": bool(value), "call": call}


def _disable_item(item: Any, label: str) -> Dict[str, Any]:
    before = base.safe_value(item, "GetClipEnabled", default=None)
    value, call = base.direct_call(item, "SetClipEnabled", False)
    after = base.safe_value(item, "GetClipEnabled", default=None)
    return {"label": label, "before": base.json_safe(before), "after": base.json_safe(after), "call": call, "ok": value is not False and after is False}


def disable_visual_overlays(timeline: Any) -> Dict[str, Any]:
    rows = []
    captions = V1.caption_items(timeline)
    if len(captions) != EXPECTED_TEXTPLUS_COUNT:
        return {"ok": False, "error": f"caption_count:{len(captions)}", "rows": rows}
    for _track, item in captions:
        row = _disable_item(item, base.item_name(item))
        rows.append(row)
        if not row["ok"]:
            return {"ok": False, "error": f"caption_disable:{row['label']}", "rows": rows}
    v4_rows = [(track, item) for track, item in base.all_video_items(timeline) if base.item_name(item) == V4.NEW_MATTE_NAME]
    if len(v4_rows) != 1:
        return {"ok": False, "error": f"v4_count:{len(v4_rows)}", "rows": rows}
    occ = _disable_item(v4_rows[0][1], V4.NEW_MATTE_NAME)
    rows.append(occ)
    return {"ok": bool(occ["ok"]), "rows": rows, "caption_toggle_count": len(captions), "occlusion_toggle_count": 1}


def _render_sequence_range(
    project: Any,
    timeline: Any,
    output_dir: Path,
    custom_name: str,
    selection: Mapping[str, Any],
    dimensions: Mapping[str, Any],
    frame_range: Sequence[int],
) -> Dict[str, Any]:
    start, end = int(frame_range[0]), int(frame_range[1])
    expected_count = end - start
    if start < 0 or expected_count <= 0:
        raise RuntimeError(f"render_range:{start}:{end}")
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
            "MarkIn": start,
            "MarkOut": end - 1,
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
            text = V4.V3.V2._status_text(raw)  # pylint: disable=protected-access
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
        if len(files) != expected_count or any(path.stat().st_size <= 0 for path in files):
            raise RuntimeError(f"render_file_count:{len(files)}:{expected_count}")
        suffixes = []
        for path in files:
            digits = "".join(ch for ch in path.stem[-12:] if ch.isdigit())
            suffixes.append(int(digits) if digits else -1)
        if suffixes != list(range(start, end)):
            raise RuntimeError(f"render_frame_indices:{suffixes[:3]}:{suffixes[-3:]}")
        return {
            "ok": True,
            "timeline_name": base.timeline_name(timeline),
            "timeline_unique_id": base.timeline_unique_id(timeline),
            "frame_range": [start, end],
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


def _helper_argv(root: Path, report_dir: Path, command: Mapping[str, Any]) -> list[str]:
    config = command.get("baked_removal") if isinstance(command.get("baked_removal"), Mapping) else {}
    python_exe = str(config.get("external_python") or "")
    if not python_exe:
        raise RuntimeError("external_python")
    return [
        python_exe,
        str((root / HELPER_RELATIVE_PATH).resolve()),
        "--base-render-dir", str((report_dir / "render_base_baked").resolve()),
        "--caption-style", str((root / STYLE_RELATIVE_PATH).resolve()),
        "--lifecycle", str((root / LIFECYCLE_RELATIVE_PATH).resolve()),
        "--tracks", str((root / TRACKS_RELATIVE_PATH).resolve()),
        "--output-root", str((report_dir / "generated_baked_removal_v1").resolve()),
        "--paddle-hub-module", str(config.get("paddle_hub_module") or "humanseg_lite"),
    ]


def _run_helper(root: Path, report_dir: Path, command: Mapping[str, Any]) -> Dict[str, Any]:
    argv = _helper_argv(root, report_dir, command)
    process = subprocess.run(argv, cwd=str(root), text=True, capture_output=True, timeout=900, check=False)
    result = {"argv": argv, "returncode": process.returncode, "stdout": process.stdout[-20000:], "stderr": process.stderr[-20000:], "ok": process.returncode == 0}
    base.write_json(report_dir / "baked_removal_helper_invocation.json", result)
    manifest_path = report_dir / "generated_baked_removal_v1" / "manifest.json"
    if process.returncode != 0 or not manifest_path.is_file():
        raise RuntimeError(f"helper:{process.returncode}:{process.stderr[-500:]}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("task_id") != TASK_ID or manifest.get("ok") is not True or manifest.get("clean_range") != list(CLEAN_RANGE):
        raise RuntimeError("helper_manifest")
    result["manifest"] = manifest
    return result


def _span(report_dir: Path) -> Dict[str, Any]:
    rgba_dir = report_dir / "generated_baked_removal_v1" / "rgba"
    return {
        "span_id": "baked_caption_restore_window_051_056_v1",
        "item_name": RESTORE_NAME,
        "timeline_frame_start": CLEAN_RANGE[0],
        "timeline_frame_end_exclusive": CLEAN_RANGE[1],
        "duration_frames": CLEAN_RANGE[1] - CLEAN_RANGE[0],
        "rgba_pattern": str((rgba_dir / "rgba_%06d.png").resolve()),
        "first_rgba_file": str((rgba_dir / f"rgba_{CLEAN_RANGE[0]:06d}.png").resolve()),
        "canonical_cue_ids": [f"sub_{value:03d}" for value in range(51, 57)],
    }


def _native_range(properties: Mapping[str, Any]) -> tuple[int, int]:
    start = base.as_int(properties.get("Start"), -1)
    end_inclusive = base.as_int(properties.get("End"), -1)
    frames = base.as_int(properties.get("Frames"), 0)
    expected_frames = CLEAN_RANGE[1] - CLEAN_RANGE[0]
    if start != CLEAN_RANGE[0] or end_inclusive != CLEAN_RANGE[1] - 1 or frames != expected_frames:
        raise RuntimeError(f"native_sequence_range:{start}:{end_inclusive}:{frames}")
    return start, end_inclusive + 1


def ensure_restore(project: Any, timeline: Any, report_dir: Path) -> Dict[str, Any]:
    existing = verify_restore(timeline)
    if existing["ok"]:
        return {"ok": True, "mutated": False, "idempotent_noop": True, "verification": existing}
    if item_inventory(timeline, RESTORE_NAME) or full.track_two_item_names(timeline):
        return {"ok": False, "mutated": False, "error": "v2_preimage", "verification": existing}
    track_setup = base.ensure_video_tracks(timeline, TARGET_TRACK)
    if not track_setup.get("ok"):
        return {"ok": False, "mutated": False, "error": "track_setup", "track_setup": track_setup}
    imported = LEGACY._import_rgba_sequence_media_pool(project, _span(report_dir), V4._legacy_args(), 24.0)  # pylint: disable=protected-access
    media_item = imported.get("item")
    if not imported.get("ok") or media_item is None or imported.get("imported") is not True:
        return {"ok": False, "mutated": False, "error": "rgba_import", "import": base.json_safe({k: v for k, v in imported.items() if k != "item"})}
    properties = imported.get("properties") if isinstance(imported.get("properties"), Mapping) else {}
    source_start, source_end = _native_range(properties)
    if str(properties.get("Alpha mode") or "") != "Straight":
        return {"ok": False, "mutated": False, "error": "alpha_mode", "properties": base.json_safe(properties), "imported_media_item": media_item, "imported_new": True}
    if str(properties.get("Input Color Space") or "") not in {"", "Project"}:
        return {"ok": False, "mutated": False, "error": "input_color_space", "properties": base.json_safe(properties), "imported_media_item": media_item, "imported_new": True}
    clip_row = {
        "media_pool_item": media_item,
        "source_start": source_start,
        "source_end_inclusive": source_end - 1,
        "source_end_frame_api": source_end,
        "api_end_semantics": "exclusive_for_rgba_sequence",
        "record_start": CLEAN_RANGE[0],
        "record_end": CLEAN_RANGE[1],
        "duration": CLEAN_RANGE[1] - CLEAN_RANGE[0],
    }
    append = LEGACY._append_media_clip_infos(project, timeline, [clip_row], TARGET_TRACK)
    items = list(append.get("detected_items") or append.get("returned_items") or [])
    if len(items) != 1:
        if items:
            base.delete_items(timeline, items)
        return {"ok": False, "mutated": True, "error": f"append_count:{len(items)}", "imported_media_item": media_item, "imported_new": True}
    item = items[0]
    name_write = LEGACY.set_timeline_item_name(item, RESTORE_NAME)
    settled = LEGACY.verify_generated_item_range_with_settle(item, CLEAN_RANGE[0], CLEAN_RANGE[1], TARGET_TRACK, timeout_sec=1.5, poll_interval_sec=0.1)
    verification = verify_restore(timeline)
    return {
        # Resolve item-name setter return shape varies across existing helpers;
        # the authoritative check is the settled item range plus the exact
        # inventory/name readback in verify_restore().
        "ok": bool(settled.get("ok") and verification.get("ok")),
        "mutated": True,
        "idempotent_noop": False,
        "track_setup": track_setup,
        "import": base.json_safe({k: v for k, v in imported.items() if k != "item"}),
        "append": base.json_safe({k: v for k, v in append.items() if k not in {"detected_items", "returned_items"}}),
        "name_write": base.json_safe(name_write),
        "range_verification": base.json_safe(settled),
        "verification": verification,
        "imported_media_item": media_item,
        "imported_new": True,
        "native_source_range": [source_start, source_end],
    }


def _run_pixel_validator(root: Path, report_dir: Path, command: Mapping[str, Any]) -> Dict[str, Any]:
    config = command.get("baked_removal") if isinstance(command.get("baked_removal"), Mapping) else {}
    python_exe = str(config.get("external_python") or "")
    output = report_dir / "pre_save_pixel_validation.json"
    argv = [
        python_exe,
        str((root / PIXEL_VALIDATOR_RELATIVE_PATH).resolve()),
        "--base-dir", str((report_dir / "render_base_baked").resolve()),
        "--generated-root", str((report_dir / "generated_baked_removal_v1").resolve()),
        "--target-base-dir", str((report_dir / "render_target_base_with_restore").resolve()),
        "--output", str(output.resolve()),
    ]
    process = subprocess.run(argv, cwd=str(root), text=True, capture_output=True, timeout=180, check=False)
    result = {"argv": argv, "returncode": process.returncode, "stdout": process.stdout[-10000:], "stderr": process.stderr[-10000:], "output": str(output), "ok": process.returncode == 0}
    base.write_json(report_dir / "pre_save_pixel_gate_invocation.json", result)
    if process.returncode != 0 or not output.is_file():
        raise RuntimeError(f"pixel_validator:{process.returncode}:{process.stderr[-500:]}")
    evidence = json.loads(output.read_text(encoding="utf-8"))
    if evidence.get("ok") is not True:
        raise RuntimeError("pixel_authority")
    result["evidence"] = evidence
    return result


def cleanup_before_save(
    project_manager: Any,
    project: Any,
    media_pool: Any,
    source: Any,
    temp_names: Sequence[str],
    target_created: bool,
    imported_media_item: Any,
    imported_new: bool,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"errors": [], "save_call_count": 0}
    try:
        if source is not None:
            selected, call = base.direct_call(project, "SetCurrentTimeline", source)
            result["restore_source"] = call
            if not selected:
                result["errors"].append("restore_source")
        for temp_name in temp_names:
            temp = base.find_timeline(project, temp_name)
            if temp is not None:
                deletion = _delete_timeline(media_pool, temp)
                result[f"delete_{temp_name}"] = deletion
                if not deletion["ok"]:
                    result["errors"].append(f"delete_temp:{temp_name}")
        target = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target_created and target is not None:
            deletion = _delete_timeline(media_pool, target)
            result["delete_target"] = deletion
            if not deletion["ok"]:
                result["errors"].append("delete_target")
        if imported_new and imported_media_item is not None:
            deletion = LEGACY._delete_media_pool_items(project, [imported_media_item])  # pylint: disable=protected-access
            result["delete_imported_media"] = base.json_safe(deletion)
            if not deletion.get("ok"):
                result["errors"].append("delete_imported_media")
        save = base.save_project(project_manager)
        result["save"] = save
        result["save_call_count"] = 1
        if not save.get("success"):
            result["errors"].append("save_cleanup")
    except BaseException as exc:
        result["errors"].append(base.compact_exception(exc))
        result["traceback"] = traceback.format_exc()
    result["ok"] = not result["errors"]
    return result


def run(resolve: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    root = base.repository_root()
    command = context.get("command") if isinstance(context, dict) else None
    if not isinstance(command, dict):
        raise ValueError("command")
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    if not run_id or command.get("task_id") != TASK_ID or command.get("mode") != MODE:
        raise ValueError("command_identity")
    report_dir = base.relative_path(root, command.get("artifacts_dir"))
    report_dir.mkdir(parents=True, exist_ok=True)
    temp_base_name = f"{TEMP_BASE_PREFIX}{run_id[-12:]}"
    temp_validate_name = f"{TEMP_VALIDATE_PREFIX}{run_id[-12:]}"
    report: Dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "ok": False,
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "final_textplus_count": None,
        "caption_mutation_count": 0,
        "baked_removal_mutation_count": 0,
        "occlusion_mutation_count": 0,
        "save_call_count": 0,
        "resolve_invocation_contract": 1,
        "visual_approval_required": True,
        "further_rollout_authorized": False,
        "failures": [],
    }
    project_manager = project = media_pool = source = None
    target_created = False
    imported_media_item = None
    imported_new = False
    saved = False
    try:
        source_contract = base.verify_source_contract(root, command)
        base.write_json(report_dir / "source_contract_verification.json", source_contract)
        config = command.get("baked_removal") if isinstance(command.get("baked_removal"), Mapping) else {}
        if config.get("source_timeline_name") != SOURCE_TIMELINE_NAME or config.get("target_timeline_name") != TARGET_TIMELINE_NAME:
            raise RuntimeError("timeline_contract")
        if config.get("context_range") != list(CONTEXT_RANGE) or config.get("clean_range") != list(CLEAN_RANGE):
            raise RuntimeError("range_contract")

        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        if base.find_timeline(project, TARGET_TIMELINE_NAME) is not None:
            raise RuntimeError("target_exists")
        source_uid = base.timeline_unique_id(source)
        source_caption_before = V1.caption_snapshot(source)
        if source_caption_before.get("count") != EXPECTED_TEXTPLUS_COUNT:
            raise RuntimeError("source_textplus")
        source_full_before = V1.stable_inventory(source)
        source_inventory_without_restore = stable_inventory_without_restore(source)
        if item_inventory(source, RESTORE_NAME):
            raise RuntimeError("source_restore_exists")
        if full.track_two_item_names(source):
            raise RuntimeError("source_v2_not_empty")
        source_v4 = V4.verify_v4_occlusion(source)
        if not source_v4.get("ok"):
            raise RuntimeError("source_v4_occlusion")
        base.write_json(report_dir / "baked_removal_preflight.json", {
            "resolve_calls": resolve_calls,
            "source_unique_id": source_uid,
            "source_caption_snapshot": source_caption_before,
            "source_v4_occlusion": source_v4,
            "source_v2_names": full.track_two_item_names(source),
            "context_range": list(CONTEXT_RANGE),
            "clean_range": list(CLEAN_RANGE),
            "target_cues": [f"sub_{value:03d}" for value in range(51, 57)],
            "architecture": "sparse_v2_restore_below_textplus_from_exact_resolve_base_render",
            "ok": True,
        })

        # 1) Exact base render from a disposable duplicate with editable overlays disabled.
        temp_value, temp_call = base.direct_call(source, "DuplicateTimeline", temp_base_name)
        temp_base = temp_value if temp_value is not None else base.find_timeline(project, temp_base_name)
        if temp_base is None:
            raise RuntimeError("duplicate_temp_base")
        if not V1.caption_snapshots_equal(source_caption_before, V1.caption_snapshot(temp_base)):
            raise RuntimeError("temp_base_caption_regression")
        toggles = disable_visual_overlays(temp_base)
        if not toggles.get("ok") or toggles.get("caption_toggle_count") != EXPECTED_TEXTPLUS_COUNT or toggles.get("occlusion_toggle_count") != 1:
            raise RuntimeError("temp_base_disable_overlays")
        dimensions = GLYPH.timeline_dimensions(temp_base, project)
        if int(dimensions.get("width") or 0) != 1080 or int(dimensions.get("height") or 0) != 1920 or abs(float(dimensions.get("frame_rate") or 0) - 24.0) > 0.001:
            raise RuntimeError(f"render_dimensions:{dimensions}")
        render_capability = V4.V3._select_png_rgb8(project)  # pylint: disable=protected-access
        selection = render_capability["selection"]
        session = V4.V3._capture_render_session(resolve, project)  # pylint: disable=protected-access
        opened, open_call = base.direct_call(resolve, "OpenPage", "deliver")
        if not opened:
            raise RuntimeError("open_deliver")
        base_render = _render_sequence_range(project, temp_base, report_dir / "render_base_baked", "base_baked_", selection, dimensions, CONTEXT_RANGE)
        restore_session = V4.V3._restore_render_session(resolve, project, session)  # pylint: disable=protected-access
        if not base_render.get("ok") or not restore_session.get("ok"):
            raise RuntimeError("base_render")
        base.write_json(report_dir / "base_render_authority.json", {
            "temporary_timeline": temp_base_name,
            "duplicate_call": temp_call,
            "overlay_toggles": toggles,
            "render_capability": render_capability,
            "dimensions": dimensions,
            "open_deliver_call": open_call,
            "render": base_render,
            "restore_session": restore_session,
            "rgb_authority": "exact_resolve_render_with_all_textplus_and_v4_occlusion_disabled",
            "ok": True,
        })

        # 2) Offline source-backed reconstruction. It must pass before target creation.
        helper = _run_helper(root, report_dir, command)

        selected_source, select_source_call = base.direct_call(project, "SetCurrentTimeline", source)
        if not selected_source:
            raise RuntimeError("restore_source_before_temp_delete")
        delete_temp_base = _delete_timeline(media_pool, temp_base)
        if not delete_temp_base.get("ok") or base.find_timeline(project, temp_base_name) is not None:
            raise RuntimeError("delete_temp_base")

        # 3) Fresh target from the accepted source; add exactly one V2 sparse restore.
        duplicate_value, duplicate_call = base.direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
        target = duplicate_value if duplicate_value is not None else base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target is None:
            raise RuntimeError("duplicate_target")
        target_created = True
        selected_target, select_target_call = base.direct_call(project, "SetCurrentTimeline", target)
        if not selected_target:
            raise RuntimeError("select_target")
        target_caption_before = V1.caption_snapshot(target)
        if not V1.caption_snapshots_equal(source_caption_before, target_caption_before):
            raise RuntimeError("target_duplicate_caption_regression")
        if stable_inventory_without_restore(target) != source_inventory_without_restore:
            raise RuntimeError("target_duplicate_inventory_regression")
        if full.track_two_item_names(target):
            raise RuntimeError("target_duplicate_v2_not_empty")

        first = ensure_restore(project, target, report_dir)
        imported_media_item = first.get("imported_media_item")
        imported_new = bool(first.get("imported_new"))
        if not first.get("ok") or not first.get("mutated"):
            raise RuntimeError("first_application")
        after_first_caption = V1.caption_snapshot(target)
        if not V1.caption_snapshots_equal(target_caption_before, after_first_caption):
            raise RuntimeError("caption_regression_after_restore")
        if stable_inventory_without_restore(target) != source_inventory_without_restore:
            raise RuntimeError("inventory_regression_after_restore")
        if not V4.verify_v4_occlusion(target).get("ok"):
            raise RuntimeError("v4_regression_after_restore")

        second = ensure_restore(project, target, report_dir)
        after_second_caption = V1.caption_snapshot(target)
        if not second.get("ok") or second.get("mutated") or second.get("idempotent_noop") is not True:
            raise RuntimeError("idempotency")
        if not V1.caption_snapshots_equal(after_first_caption, after_second_caption):
            raise RuntimeError("caption_regression_idempotency")
        restore_verify = verify_restore(target)
        if not restore_verify.get("ok"):
            raise RuntimeError("restore_pre_save")
        base.write_json(report_dir / "baked_removal_application.json", {
            "select_source_call": select_source_call,
            "delete_temp_base": delete_temp_base,
            "duplicate_target_call": duplicate_call,
            "select_target_call": select_target_call,
            "helper_manifest": helper["manifest"],
            "first_application": base.json_safe({k: v for k, v in first.items() if k != "imported_media_item"}),
            "second_application": base.json_safe({k: v for k, v in second.items() if k != "imported_media_item"}),
            "restore_verification": restore_verify,
            "checks": {
                "caption_frozen": V1.caption_snapshots_equal(source_caption_before, after_second_caption),
                "inventory_frozen_except_restore": stable_inventory_without_restore(target) == source_inventory_without_restore,
                "v4_occlusion_preserved": V4.verify_v4_occlusion(target).get("ok") is True,
                "v2_restore_only": restore_verify.get("ok") is True,
                "idempotent_second_noop": second.get("idempotent_noop") is True and second.get("mutated") is False,
                "native_sequence_range_exact": first.get("native_source_range") == list(CLEAN_RANGE),
            },
            "ok": True,
        })

        # 4) Independent pre-save pixel gate on another disposable duplicate.
        validate_value, validate_call = base.direct_call(target, "DuplicateTimeline", temp_validate_name)
        temp_validate = validate_value if validate_value is not None else base.find_timeline(project, temp_validate_name)
        if temp_validate is None:
            raise RuntimeError("duplicate_temp_validate")
        if not verify_restore(temp_validate).get("ok"):
            raise RuntimeError("temp_validate_restore")
        validation_toggles = disable_visual_overlays(temp_validate)
        if not validation_toggles.get("ok"):
            raise RuntimeError("temp_validate_disable_overlays")
        session2 = V4.V3._capture_render_session(resolve, project)  # pylint: disable=protected-access
        opened2, open_call2 = base.direct_call(resolve, "OpenPage", "deliver")
        if not opened2:
            raise RuntimeError("open_deliver_validate")
        target_base_render = _render_sequence_range(project, temp_validate, report_dir / "render_target_base_with_restore", "target_base_with_restore_", selection, dimensions, CLEAN_RANGE)
        restore_session2 = V4.V3._restore_render_session(resolve, project, session2)  # pylint: disable=protected-access
        if not target_base_render.get("ok") or not restore_session2.get("ok"):
            raise RuntimeError("target_base_render")
        selected_target2, select_target2_call = base.direct_call(project, "SetCurrentTimeline", target)
        if not selected_target2:
            raise RuntimeError("restore_target_before_validate_delete")
        delete_temp_validate = _delete_timeline(media_pool, temp_validate)
        if not delete_temp_validate.get("ok") or base.find_timeline(project, temp_validate_name) is not None:
            raise RuntimeError("delete_temp_validate")
        pixel_gate = _run_pixel_validator(root, report_dir, command)
        if not pixel_gate.get("ok"):
            raise RuntimeError("pixel_gate")
        base.write_json(report_dir / "pre_save_render_validation.json", {
            "duplicate_call": validate_call,
            "overlay_toggles": validation_toggles,
            "open_deliver_call": open_call2,
            "render": target_base_render,
            "restore_session": restore_session2,
            "select_target_call": select_target2_call,
            "delete_temp_validate": delete_temp_validate,
            "pixel_gate": pixel_gate,
            "ok": True,
        })

        save = base.save_project(project_manager)
        report["save_call_count"] = 1
        saved = True
        if not save.get("success"):
            raise RuntimeError("save")

        project_manager, project, media_pool, reacquire_calls = base.get_project(resolve)
        source_after = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        target_after = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if source_after is None or target_after is None:
            raise RuntimeError("reacquire")
        source_caption_after = V1.caption_snapshot(source_after)
        target_caption_after = V1.caption_snapshot(target_after)
        persistent_restore = verify_restore(target_after)
        persistent_v4 = V4.verify_v4_occlusion(target_after)
        checks = {
            "source_unique_id_unchanged": base.timeline_unique_id(source_after) == source_uid,
            "source_inventory_unchanged": V1.stable_inventory(source_after) == source_full_before,
            "source_caption_unchanged": V1.caption_snapshots_equal(source_caption_before, source_caption_after),
            "target_caption_unchanged": V1.caption_snapshots_equal(source_caption_before, target_caption_after),
            "target_inventory_unchanged_except_restore": stable_inventory_without_restore(target_after) == source_inventory_without_restore,
            "target_restore_exact": persistent_restore.get("ok") is True,
            "target_v4_occlusion_preserved": persistent_v4.get("ok") is True,
            "textplus_114": target_caption_after.get("count") == EXPECTED_TEXTPLUS_COUNT,
            "one_save": report["save_call_count"] == 1,
            "idempotency": second.get("idempotent_noop") is True and second.get("mutated") is False,
            "helper_authority": helper["manifest"].get("ok") is True,
            "pixel_authority": pixel_gate.get("evidence", {}).get("ok") is True,
            "temp_timelines_deleted": base.find_timeline(project, temp_base_name) is None and base.find_timeline(project, temp_validate_name) is None,
        }
        persistent = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "reacquire_calls": reacquire_calls,
            "save": save,
            "source_caption_snapshot_before": source_caption_before,
            "source_caption_snapshot_after": source_caption_after,
            "target_caption_snapshot": target_caption_after,
            "restore": persistent_restore,
            "v4_occlusion": persistent_v4,
            "checks": checks,
            "visual_approval_required": True,
            "further_rollout_authorized": False,
            "ok": all(checks.values()),
        }
        base.write_json(report_dir / "persistent_readback.json", persistent)
        if not persistent["ok"]:
            raise RuntimeError("persistent_readback")

        report.update({
            "ok": True,
            "final_textplus_count": EXPECTED_TEXTPLUS_COUNT,
            "caption_mutation_count": 0,
            "baked_removal_mutation_count": 1,
            "occlusion_mutation_count": 0,
            "source_timeline_unchanged": True,
            "v4_occlusion_preserved": True,
            "motion_fade_and_size_fix_preserved": True,
            "restore_track": TARGET_TRACK,
            "restore_range": list(CLEAN_RANGE),
            "target_timeline_kept": True,
            "persistent_readback_ok": True,
            "idempotency_ok": True,
            "pre_save_pixel_authority_ok": True,
        })
        return report
    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc))
        report["traceback"] = traceback.format_exc()
        if not saved and project_manager is not None and project is not None and media_pool is not None:
            cleanup = cleanup_before_save(
                project_manager,
                project,
                media_pool,
                source,
                (temp_base_name, temp_validate_name),
                target_created,
                imported_media_item,
                imported_new,
            )
            base.write_json(report_dir / "failure_cleanup.json", cleanup)
            report["save_call_count"] = int(cleanup.get("save_call_count") or 0)
            report["failure_cleanup_ok"] = cleanup.get("ok") is True
            report["failed_target_retained"] = False if cleanup.get("ok") else None
        elif saved:
            report["post_save_failure_target_retained"] = True
        return report
