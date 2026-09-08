"""Final occlusion composition V4: native image-sequence indexing correction.

V3 proved the sparse mask/RGB authority but its imported image sequence was
appended with source frames 0..27 even though the MediaPoolItem native range
was 426..453. Resolve clamped that invalid trim to the first sequence image.
V4 starts again from the accepted 114-Text+ source, regenerates the same sparse
Resolve-backed restore, appends the sequence with its native 426..454 source
range, and runs rendered pixel authority before the single project save.
"""
from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Mapping

TASK_ID = "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V4"
MODE = "FINAL_OCCLUSION_COMPOSITION_V4"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/final_occlusion_composition_v4.py"
PIXEL_VALIDATOR_RELATIVE = "scripts/analysis/validate_final_occlusion_pixel_restore_v4.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
REJECTED_V1_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v1"
REJECTED_V2_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v2"
REJECTED_V3_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v3"
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v4"
TEMP_TIMELINE_PREFIX = "VC_OCCLUSION_V4_RENDER_"
EXPECTED_TEXTPLUS_COUNT = 114
TARGET_CAPTION_NAME = "VC_TEXTPLUS_0052_sub_052"
TARGET_RANGE = (426, 454)
TARGET_DURATION = 28
OLD_MATTE_NAME = "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052"
V2_MATTE_NAME = "VC_OCCLUSION_RGBA_matte_span_0001_temporal_v2_sub_0052"
V3_MATTE_NAME = "VC_OCCLUSION_PIXEL_RESTORE_matte_span_0001_v3_sub_0052"
NEW_MATTE_NAME = "VC_OCCLUSION_PIXEL_RESTORE_matte_span_0001_v4_sub_0052"
SOURCE_VIDEO_RELATIVE = "input/DZsqH7auhjt.mp4"
SOURCE_VIDEO_SHA256 = "fd60f596fb09031d8fa41071691cbdc1884edb32fd79f436f6be1df1ca186635"
ANCHOR_DIR_RELATIVE = "data/DZsqH7auhjt/analysis/foreground_matte_spans/matte_span_0001"
ANCHOR_HASHES = {
    429: "fbea2275e7f1edb16e1e3c2130c587a5948968e1af847d7abb36d41a3cf9a971",
    430: "72f4f8cd0e7ecae13c8d28f3d1e44a77c890a730f591668430e0c613d84287b9",
    431: "b1d5a8e481d2370355d82dc2d8e9ad7bb9bf0b4e5e9e162e97561fafd15f3d03",
    432: "8f07161e5e1d0f597f9268efa851f700452ebd0d89858aa40721f1ef96979883",
    433: "5831a4d86ba3b4bc0fd50908f46a4d8ecadfb9f7d304ecaac2d921ecf53ea74f",
}
STABLE_INVENTORY_FIELDS = ("name", "track_index", "start", "end", "duration", "media_pool_item_name", "fusion_comp_count")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
V3 = _load("vc_final_occlusion_v3_for_v4", HERE / "final_occlusion_composition_v3.py")
V1 = V3.V1
full = V3.full
base = V3.base
LEGACY = V3.LEGACY
GLYPH = V3.GLYPH
OCCLUSION_NAMES = {OLD_MATTE_NAME, V2_MATTE_NAME, V3_MATTE_NAME, NEW_MATTE_NAME}


def item_inventory(timeline: Any, name: str) -> list[Dict[str, Any]]:
    return sorted(
        [base.item_summary(int(track), item) for track, item in base.all_video_items(timeline) if base.item_name(item) == name],
        key=lambda row: (int(row.get("track_index") or 0), int(row.get("start") or 0)),
    )


def stable_inventory_without_occlusion(timeline: Any) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for track, item in base.all_video_items(timeline):
        if base.item_name(item) in OCCLUSION_NAMES:
            continue
        summary = base.item_summary(int(track), item)
        rows.append(tuple(summary.get(field) for field in STABLE_INVENTORY_FIELDS))
    return sorted(rows, key=lambda row: tuple("" if value is None else str(value) for value in row))


def verify_source_preimage(timeline: Any) -> Dict[str, Any]:
    old = item_inventory(timeline, OLD_MATTE_NAME)
    v2 = item_inventory(timeline, V2_MATTE_NAME)
    v3 = item_inventory(timeline, V3_MATTE_NAME)
    v4 = item_inventory(timeline, NEW_MATTE_NAME)
    ok = bool(
        len(old) == 1
        and [old[0].get("start"), old[0].get("end")] == [429, 434]
        and int(old[0].get("duration") or -1) == 5
        and not v2 and not v3 and not v4
    )
    return {"old": old, "v2": v2, "v3": v3, "v4": v4, "ok": ok}


def verify_v4_occlusion(timeline: Any) -> Dict[str, Any]:
    old = item_inventory(timeline, OLD_MATTE_NAME)
    v2 = item_inventory(timeline, V2_MATTE_NAME)
    v3 = item_inventory(timeline, V3_MATTE_NAME)
    rows = item_inventory(timeline, NEW_MATTE_NAME)
    max_caption = V1.caption_track_max(timeline)
    ok = bool(
        not old and not v2 and not v3 and len(rows) == 1
        and [rows[0].get("start"), rows[0].get("end")] == list(TARGET_RANGE)
        and int(rows[0].get("duration") or -1) == TARGET_DURATION
        and int(rows[0].get("track_index") or 0) > max_caption
        and str(rows[0].get("media_pool_item_name") or "") == NEW_MATTE_NAME
    )
    return {"old": old, "v2": v2, "v3": v3, "rows": rows, "max_caption_track": max_caption, "ok": ok}


def _find_caption(timeline: Any) -> tuple[int, Any]:
    rows = [(int(track), item) for track, item in base.all_video_items(timeline) if base.item_name(item) == TARGET_CAPTION_NAME]
    if len(rows) != 1:
        raise RuntimeError(f"target_caption_count:{len(rows)}")
    track, item = rows[0]
    summary = base.item_summary(track, item)
    if [summary.get("start"), summary.get("end")] != list(TARGET_RANGE) or int(summary.get("duration") or -1) != TARGET_DURATION:
        raise RuntimeError(f"target_caption_range:{summary}")
    return track, item


def _remove_old_matte(timeline: Any) -> Dict[str, Any]:
    rows = [(int(track), item) for track, item in base.all_video_items(timeline) if base.item_name(item) == OLD_MATTE_NAME]
    if len(rows) != 1:
        return {"ok": False, "error": f"old_matte_count:{len(rows)}"}
    summary = base.item_summary(rows[0][0], rows[0][1])
    if [summary.get("start"), summary.get("end")] != [429, 434]:
        return {"ok": False, "error": "old_matte_range", "summary": summary}
    deletion = base.delete_items(timeline, [rows[0][1]])
    time.sleep(0.15)
    return {"ok": bool(deletion.get("ok") and not item_inventory(timeline, OLD_MATTE_NAME)), "deletion": deletion, "summary": summary}


def _legacy_args() -> SimpleNamespace:
    # V4 must never reuse a stale media-pool item from a failed experiment.
    return SimpleNamespace(
        caption_occlusion_reuse_media_pool_items=False,
        caption_occlusion_set_straight_alpha=True,
        caption_occlusion_alpha_mode="Straight",
        caption_occlusion_verify_settle_timeout_sec=1.5,
        caption_occlusion_verify_poll_interval_sec=0.1,
    )


def _span(report_dir: Path) -> Dict[str, Any]:
    rgba_dir = report_dir / "generated_pixel_restore_v3" / "rgba"
    return {
        "span_id": "matte_span_0001_pixel_restore_v4",
        "item_name": NEW_MATTE_NAME,
        "timeline_frame_start": TARGET_RANGE[0],
        "timeline_frame_end_exclusive": TARGET_RANGE[1],
        "duration_frames": TARGET_DURATION,
        "rgba_pattern": str((rgba_dir / "rgba_%06d.png").resolve()),
        "first_rgba_file": str((rgba_dir / f"rgba_{TARGET_RANGE[0]:06d}.png").resolve()),
        "canonical_cue_ids": ["sub_0052"],
    }


def native_source_range(properties: Mapping[str, Any]) -> tuple[int, int]:
    start = base.as_int(properties.get("Start"), -1)
    end_inclusive = base.as_int(properties.get("End"), -1)
    frames = base.as_int(properties.get("Frames"), 0)
    if start != TARGET_RANGE[0] or end_inclusive != TARGET_RANGE[1] - 1 or frames != TARGET_DURATION:
        raise RuntimeError(f"native_sequence_range:{start}:{end_inclusive}:{frames}")
    return start, end_inclusive + 1


def append_native_index_sequence(
    project: Any,
    timeline: Any,
    media_pool_item: Any,
    target_track: int,
    properties: Mapping[str, Any],
) -> Dict[str, Any]:
    """Append the imported sequence using its native 426..454 source range.

    V3 used 0..28. The imported MediaPoolItem itself reported Start=426,
    End=453, Frames=28, so Resolve clamped the invalid trim to sequence frame
    426. V4 has no fallback: source range must equal the MediaPoolItem's native
    indices, and rendered pixel authority must pass before save.
    """
    source_start, source_end_exclusive = native_source_range(properties)
    clip_row = {
        "media_pool_item": media_pool_item,
        "source_start": source_start,
        "source_end_inclusive": source_end_exclusive - 1,
        "source_end_frame_api": source_end_exclusive,
        "api_end_semantics": "exclusive_for_rgba_sequence",
        "record_start": TARGET_RANGE[0],
        "record_end": TARGET_RANGE[1],
        "duration": TARGET_DURATION,
    }
    append = LEGACY._append_media_clip_infos(project, timeline, [clip_row], target_track)
    items = list(append.get("detected_items") or append.get("returned_items") or [])
    result: Dict[str, Any] = {
        "attempted": True,
        "native_media_range": [source_start, source_end_exclusive],
        "source_range_used": [source_start, source_end_exclusive],
        "record_range": list(TARGET_RANGE),
        "target_track": target_track,
        "append": base.json_safe({k: v for k, v in append.items() if k not in {"detected_items", "returned_items"}}),
        "detected_count": len(items),
        "item": None,
        "ok": False,
    }
    if len(items) != 1:
        if items:
            result["rollback"] = base.json_safe(base.delete_items(timeline, items))
        result["error"] = f"append_count:{len(items)}"
        return result
    item = items[0]
    result["name_write"] = base.json_safe(LEGACY.set_timeline_item_name(item, NEW_MATTE_NAME))
    verify = LEGACY.verify_generated_item_range_with_settle(
        item, TARGET_RANGE[0], TARGET_RANGE[1], target_track,
        timeout_sec=1.5, poll_interval_sec=0.1,
    )
    result["verification"] = base.json_safe(verify)
    if not verify.get("ok"):
        result["rollback"] = base.json_safe(base.delete_items(timeline, [item]))
        result["error"] = "range_verification"
        return result
    result["item"] = item
    result["ok"] = True
    return result


def ensure_v4_occlusion(project: Any, timeline: Any, report_dir: Path) -> Dict[str, Any]:
    existing = verify_v4_occlusion(timeline)
    if existing["ok"]:
        return {"ok": True, "mutated": False, "idempotent_noop": True, "verification": existing}
    preimage = verify_source_preimage(timeline)
    if not preimage["ok"]:
        return {"ok": False, "mutated": False, "error": "v4_preimage", "preimage": preimage}

    old_item = next(item for _track, item in base.all_video_items(timeline) if base.item_name(item) == OLD_MATTE_NAME)
    target_track = V1.caption_track_max(timeline) + 1
    track_setup = base.ensure_video_tracks(timeline, target_track)
    if not track_setup.get("ok"):
        return {"ok": False, "mutated": False, "error": "track_setup", "track_setup": track_setup}

    imported = LEGACY._import_rgba_sequence_media_pool(project, _span(report_dir), _legacy_args(), 24.0)
    media_item = imported.get("item")
    if not imported.get("ok") or media_item is None or imported.get("imported") is not True:
        return {"ok": False, "mutated": False, "error": "rgba_import", "import": base.json_safe({k: v for k, v in imported.items() if k != "item"})}
    properties = imported.get("properties") if isinstance(imported.get("properties"), Mapping) else {}
    try:
        source_range = native_source_range(properties)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "mutated": False, "error": base.compact_exception(exc), "imported_media_item": media_item, "imported_new": True}
    if str(properties.get("Alpha mode") or "") != "Straight":
        return {"ok": False, "mutated": False, "error": "alpha_mode", "properties": base.json_safe(properties), "imported_media_item": media_item, "imported_new": True}

    deletion = base.delete_items(timeline, [old_item])
    time.sleep(0.15)
    if not deletion.get("ok") or item_inventory(timeline, OLD_MATTE_NAME):
        return {"ok": False, "mutated": True, "error": "old_matte_delete", "deletion": deletion, "imported_media_item": media_item, "imported_new": True}

    appended = append_native_index_sequence(project, timeline, media_item, target_track, properties)
    verification = verify_v4_occlusion(timeline)
    return {
        "ok": bool(appended.get("ok") and verification.get("ok")),
        "mutated": True,
        "idempotent_noop": False,
        "target_track": target_track,
        "track_setup": track_setup,
        "import": base.json_safe({k: v for k, v in imported.items() if k != "item"}),
        "imported_media_item": media_item,
        "imported_new": True,
        "native_source_range": list(source_range),
        "deletion": deletion,
        "append": base.json_safe({k: v for k, v in appended.items() if k != "item"}),
        "verification": verification,
    }


def _delete_timeline(media_pool: Any, timeline: Any) -> Dict[str, Any]:
    value, call = base.direct_call(media_pool, "DeleteTimelines", [timeline])
    return {"ok": bool(value), "call": call}


def _render_final(resolve: Any, project: Any, target: Any, report_dir: Path, selection: Mapping[str, Any], dimensions: Mapping[str, Any]) -> Dict[str, Any]:
    session = V3._capture_render_session(resolve, project)
    opened, call = base.direct_call(resolve, "OpenPage", "deliver")
    if not opened:
        raise RuntimeError("open_deliver_final")
    render = V3._render(project, target, report_dir / "render_target_occlusion_v4", "target_occlusion_v4_", selection, dimensions)
    restore = V3._restore_render_session(resolve, project, session)
    return {"render": render, "restore": restore, "open_call": call, "ok": bool(render.get("ok") and restore.get("ok"))}


def _run_pre_save_pixel_gate(root: Path, report_dir: Path, command: Mapping[str, Any]) -> Dict[str, Any]:
    python_exe = str(((command.get("occlusion") or {}).get("external_python") or ""))
    if not python_exe:
        raise RuntimeError("external_python")
    output = report_dir / "pre_save_pixel_validation_v4.json"
    argv = [
        python_exe,
        str((root / PIXEL_VALIDATOR_RELATIVE).resolve()),
        "--with-dir", str((report_dir / "render_with_come_no_oldmatte").resolve()),
        "--without-dir", str((report_dir / "render_without_come_no_oldmatte").resolve()),
        "--target-dir", str((report_dir / "render_target_occlusion_v4").resolve()),
        "--generated-root", str((report_dir / "generated_pixel_restore_v3").resolve()),
        "--output", str(output.resolve()),
    ]
    proc = subprocess.run(argv, cwd=str(root), text=True, capture_output=True, timeout=180, check=False)
    result = {
        "argv": argv,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-10000:],
        "stderr": proc.stderr[-10000:],
        "output": str(output),
        "ok": proc.returncode == 0,
    }
    base.write_json(report_dir / "pre_save_pixel_gate_invocation.json", result)
    if not output.is_file():
        raise RuntimeError("pre_save_pixel_output_missing")
    evidence = json.loads(output.read_text(encoding="utf-8"))
    if proc.returncode != 0 or evidence.get("ok") is not True:
        raise RuntimeError("pre_save_pixel_authority")
    result["evidence"] = evidence
    return result


def cleanup_before_save(
    project_manager: Any,
    project: Any,
    media_pool: Any,
    source: Any,
    temp_name: str,
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
        temp = base.find_timeline(project, temp_name)
        if temp is not None:
            deletion = _delete_timeline(media_pool, temp)
            result["delete_temp"] = deletion
            if not deletion["ok"]:
                result["errors"].append("delete_temp")
        target = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target_created and target is not None:
            deletion = _delete_timeline(media_pool, target)
            result["delete_target"] = deletion
            if not deletion["ok"]:
                result["errors"].append("delete_target")
        if imported_new and imported_media_item is not None:
            deletion = LEGACY._delete_media_pool_items(project, [imported_media_item])
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
    temp_name = f"{TEMP_TIMELINE_PREFIX}{run_id[-12:]}"
    report: Dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "ok": False,
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "caption_mutation_count": 0,
        "temporary_caption_toggle_count": 0,
        "occlusion_mutation_count": 0,
        "save_call_count": 0,
        "resolve_invocation_contract": 1,
        "visual_approval_required": True,
        "further_rollout_authorized": False,
        "started_at": base.utc_now(),
        "failures": [],
    }
    project_manager = project = media_pool = source = None
    temp = None
    target_created = False
    imported_media_item = None
    imported_new = False
    saved = False
    try:
        source_contract = base.verify_source_contract(root, command)
        base.write_json(report_dir / "source_contract_verification.json", source_contract)
        config = command.get("occlusion") if isinstance(command.get("occlusion"), Mapping) else {}

        video = root / SOURCE_VIDEO_RELATIVE
        video_actual = base.raw_sha256(video) if video.is_file() else ""
        if video_actual != SOURCE_VIDEO_SHA256 or config.get("source_video_sha256") != SOURCE_VIDEO_SHA256:
            raise RuntimeError("source_video_hash")

        anchor_expected = config.get("anchor_mask_hashes") if isinstance(config.get("anchor_mask_hashes"), Mapping) else {}
        anchor_rows = []
        for frame, expected in ANCHOR_HASHES.items():
            relative = f"{ANCHOR_DIR_RELATIVE}/mask_{frame:06d}.png"
            path = root / relative
            actual = base.raw_sha256(path) if path.is_file() else ""
            matched = actual == expected == str(anchor_expected.get(relative) or "")
            anchor_rows.append({"frame": frame, "path": relative, "expected": expected, "actual": actual, "matched": matched})
            if not matched:
                raise RuntimeError(f"anchor_hash:{frame}")
        base.write_json(report_dir / "clean_person_anchor_verification.json", {"rows": anchor_rows, "ok": True})

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
        source_preimage = verify_source_preimage(source)
        if not source_preimage["ok"]:
            raise RuntimeError("source_preimage")
        if full.track_two_item_names(source):
            raise RuntimeError("source_v2_not_empty")
        _find_caption(source)
        base.write_json(report_dir / "occlusion_v4_preflight.json", {
            "resolve_calls": resolve_calls,
            "source_unique_id": source_uid,
            "source_caption_snapshot": source_caption_before,
            "source_preimage": source_preimage,
            "source_non_occlusion_inventory": source_nonocc_before,
            "rejected_timelines_never_source": [REJECTED_V1_TIMELINE_NAME, REJECTED_V2_TIMELINE_NAME, REJECTED_V3_TIMELINE_NAME],
            "root_cause_contract": "native_media_start_426_not_relative_zero",
            "ok": True,
        })

        # Disposable render authority.
        temp_value, temp_call = base.direct_call(source, "DuplicateTimeline", temp_name)
        temp = temp_value if temp_value is not None else base.find_timeline(project, temp_name)
        if temp is None:
            raise RuntimeError("duplicate_temp")
        if not V1.caption_snapshots_equal(source_caption_before, V1.caption_snapshot(temp)):
            raise RuntimeError("temp_duplicate_caption_regression")
        removed = _remove_old_matte(temp)
        if not removed.get("ok"):
            raise RuntimeError("temp_remove_old_matte")
        if stable_inventory_without_occlusion(temp) != source_nonocc_before:
            raise RuntimeError("temp_nonocc_regression")

        dimensions = GLYPH.timeline_dimensions(temp, project)
        if int(dimensions.get("width") or 0) != 1080 or int(dimensions.get("height") or 0) != 1920 or abs(float(dimensions.get("frame_rate") or 0) - 24.0) > 0.001:
            raise RuntimeError(f"render_dimensions:{dimensions}")
        render_capability = V3._select_png_rgb8(project)
        selection = render_capability["selection"]
        session = V3._capture_render_session(resolve, project)
        opened, open_call = base.direct_call(resolve, "OpenPage", "deliver")
        if not opened:
            raise RuntimeError("open_deliver")
        with_render = V3._render(project, temp, report_dir / "render_with_come_no_oldmatte", "with_come_no_oldmatte_", selection, dimensions)
        if not with_render.get("ok"):
            raise RuntimeError("with_come_render")
        _track, target_caption = _find_caption(temp)
        before_enabled = base.safe_value(target_caption, "GetClipEnabled", default=None)
        value, toggle_call = base.direct_call(target_caption, "SetClipEnabled", False)
        after_enabled = base.safe_value(target_caption, "GetClipEnabled", default=None)
        if value is False or before_enabled is False or after_enabled is not False:
            raise RuntimeError("temporary_caption_disable")
        report["temporary_caption_toggle_count"] = 1
        without_render = V3._render(project, temp, report_dir / "render_without_come_no_oldmatte", "without_come_no_oldmatte_", selection, dimensions)
        if not without_render.get("ok"):
            raise RuntimeError("without_come_render")
        restore = V3._restore_render_session(resolve, project, session)
        if not restore.get("ok"):
            raise RuntimeError("restore_render_session")
        base.write_json(report_dir / "render_authority_v4.json", {
            "temporary_timeline": temp_name,
            "duplicate_call": temp_call,
            "old_matte_removal": removed,
            "target_caption": TARGET_CAPTION_NAME,
            "temporary_toggle_call": toggle_call,
            "temporary_toggle_before": base.json_safe(before_enabled),
            "temporary_toggle_after": base.json_safe(after_enabled),
            "render_capability": render_capability,
            "dimensions": dimensions,
            "open_deliver_call": open_call,
            "with_come": with_render,
            "without_come": without_render,
            "restore": restore,
            "rgb_authority": "resolve_render_with_target_come_disabled",
            "ok": True,
        })

        # Reuse the proven V3 sparse-mask builder; only sequence indexing changes.
        helper = V3._run_helper(root, report_dir, command)

        selected_source, select_source_call = base.direct_call(project, "SetCurrentTimeline", source)
        if not selected_source:
            raise RuntimeError("restore_source_before_temp_delete")
        temp_delete = _delete_timeline(media_pool, temp)
        if not temp_delete["ok"] or base.find_timeline(project, temp_name) is not None:
            raise RuntimeError("delete_temp")
        temp = None

        duplicate_value, duplicate_call = base.direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
        target = duplicate_value if duplicate_value is not None else base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target is None:
            raise RuntimeError("duplicate_target")
        target_created = True
        selected_target, select_target_call = base.direct_call(project, "SetCurrentTimeline", target)
        if not selected_target:
            raise RuntimeError("select_target")

        target_caption_duplicate = V1.caption_snapshot(target)
        if not V1.caption_snapshots_equal(source_caption_before, target_caption_duplicate):
            raise RuntimeError("target_duplicate_caption_regression")
        if stable_inventory_without_occlusion(target) != source_nonocc_before:
            raise RuntimeError("target_duplicate_nonocc_regression")

        first = ensure_v4_occlusion(project, target, report_dir)
        imported_media_item = first.get("imported_media_item")
        imported_new = bool(first.get("imported_new"))
        after_first_caption = V1.caption_snapshot(target)
        first_caption_ok = V1.caption_snapshots_equal(target_caption_duplicate, after_first_caption)
        first_nonocc_ok = stable_inventory_without_occlusion(target) == source_nonocc_before
        if not first.get("ok") or not first.get("mutated") or not first_caption_ok or not first_nonocc_ok:
            raise RuntimeError("v4_first_application")

        second = ensure_v4_occlusion(project, target, report_dir)
        after_second_caption = V1.caption_snapshot(target)
        second_caption_ok = V1.caption_snapshots_equal(after_first_caption, after_second_caption)
        second_nonocc_ok = stable_inventory_without_occlusion(target) == source_nonocc_before
        if not second.get("ok") or second.get("mutated") or second.get("idempotent_noop") is not True or not second_caption_ok or not second_nonocc_ok:
            raise RuntimeError("v4_idempotency")
        pre_save = verify_v4_occlusion(target)
        if not pre_save["ok"]:
            raise RuntimeError("v4_pre_save")

        base.write_json(report_dir / "occlusion_v4_application.json", {
            "select_source_call": select_source_call,
            "temp_delete": temp_delete,
            "duplicate_target_call": duplicate_call,
            "select_target_call": select_target_call,
            "helper_manifest": helper["manifest"],
            "first_application": base.json_safe({k: v for k, v in first.items() if k != "imported_media_item"}),
            "second_application": base.json_safe({k: v for k, v in second.items() if k != "imported_media_item"}),
            "checks": {
                "caption_unchanged_after_first": first_caption_ok,
                "caption_unchanged_after_second": second_caption_ok,
                "non_occlusion_inventory_after_first": first_nonocc_ok,
                "non_occlusion_inventory_after_second": second_nonocc_ok,
                "idempotent_second_noop": second.get("idempotent_noop") is True and second.get("mutated") is False,
                "native_source_range_426_454": first.get("native_source_range") == [426, 454],
                "v4_matte_exact": pre_save["ok"],
            },
            "caption_snapshot_before": target_caption_duplicate,
            "caption_snapshot_after": after_second_caption,
            "ok": True,
        })

        final_render = _render_final(resolve, project, target, report_dir, selection, dimensions)
        base.write_json(report_dir / "final_render_v4.json", final_render)
        if not final_render.get("ok"):
            raise RuntimeError("final_render_v4")

        # Critical V4 difference: prove pixels BEFORE the one project save.
        pixel_gate = _run_pre_save_pixel_gate(root, report_dir, command)
        if not pixel_gate.get("ok"):
            raise RuntimeError("pre_save_pixel_gate")

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
        target_caption_persistent = V1.caption_snapshot(target_after)
        target_occ = verify_v4_occlusion(target_after)
        checks = {
            "source_unique_id_unchanged": base.timeline_unique_id(source_after) == source_uid,
            "source_full_inventory_unchanged": V1.stable_inventory(source_after) == source_full_before,
            "source_caption_unchanged": V1.caption_snapshots_equal(source_caption_before, source_caption_after),
            "target_caption_unchanged": V1.caption_snapshots_equal(source_caption_before, target_caption_persistent),
            "target_non_occlusion_inventory_unchanged": stable_inventory_without_occlusion(target_after) == source_nonocc_before,
            "target_v4_occlusion_exact": target_occ["ok"],
            "textplus_114": target_caption_persistent["count"] == EXPECTED_TEXTPLUS_COUNT,
            "v2_track_empty": not full.track_two_item_names(target_after),
            "temp_deleted": base.find_timeline(project, temp_name) is None,
            "one_save": report["save_call_count"] == 1,
            "idempotency_pre_save": second.get("idempotent_noop") is True and second.get("mutated") is False,
            "helper_manifest_ok": helper["manifest"].get("ok") is True,
            "pre_save_pixel_authority": pixel_gate.get("evidence", {}).get("ok") is True,
            "final_render_generated": final_render.get("ok") is True,
        }
        persistent = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "reacquire_calls": reacquire_calls,
            "save": save,
            "source_caption_snapshot_before": source_caption_before,
            "source_caption_snapshot_after": source_caption_after,
            "target_caption_snapshot": target_caption_persistent,
            "occlusion": target_occ,
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
            "occlusion_mutation_count": 1,
            "source_timeline_unchanged": True,
            "caption_baseline_unchanged": True,
            "persistent_readback_ok": True,
            "idempotency_ok": True,
            "pixel_restore_helper_ok": True,
            "pre_save_pixel_authority_ok": True,
            "final_render_evidence_generated": True,
            "occlusion_target_track": int(target_occ["rows"][0]["track_index"]),
            "target_timeline_kept": True,
            "native_sequence_source_range": [426, 454],
        })
        return report
    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc))
        report["traceback"] = traceback.format_exc()
        if not saved and project_manager is not None and project is not None and media_pool is not None:
            cleanup = cleanup_before_save(
                project_manager, project, media_pool, source, temp_name,
                target_created, imported_media_item, imported_new,
            )
            base.write_json(report_dir / "failure_cleanup.json", cleanup)
            report["save_call_count"] = int(cleanup.get("save_call_count") or 0)
            report["failure_cleanup_ok"] = cleanup.get("ok") is True
            report["failed_target_retained"] = False if cleanup.get("ok") else None
        elif saved:
            report["post_save_failure_target_retained"] = True
        return report
