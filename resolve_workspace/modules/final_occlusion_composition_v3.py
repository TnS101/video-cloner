"""Sparse, source-backed final occlusion composition V3.

V1/V2 proved timeline safety but failed human review because their RGBA assets
contained full foreground RGB and contaminated mask geometry. V3 starts again
from the accepted 114-Text+ source timeline. It uses a disposable duplicate to
render the exact target section twice after removing the legacy matte: once with
all captions and once with only the target COME Text+ disabled. An external
OpenCV helper intersects that exact caption difference with clean HumanSeg
person masks extended by global affine transforms only, then emits a sparse
RGBA pixel-restore sequence whose RGB is the Resolve render with COME disabled.

No accepted caption item is modified. Rejected V1/V2 timelines are never source.
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

TASK_ID = "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V3"
MODE = "FINAL_OCCLUSION_COMPOSITION_V3"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/final_occlusion_composition_v3.py"
HELPER_RELATIVE_PATH = "scripts/analysis/build_final_occlusion_pixel_restore_v3.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
REJECTED_V1_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v1"
REJECTED_V2_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v2"
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v3"
TEMP_TIMELINE_PREFIX = "VC_OCCLUSION_V3_RENDER_"
EXPECTED_TEXTPLUS_COUNT = 114
TARGET_CAPTION_NAME = "VC_TEXTPLUS_0052_sub_052"
TARGET_RANGE = (426, 454)
TARGET_DURATION = 28
OLD_MATTE_NAME = "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052"
OLD_MATTE_RANGE = (429, 434)
V2_MATTE_NAME = "VC_OCCLUSION_RGBA_matte_span_0001_temporal_v2_sub_0052"
NEW_MATTE_NAME = "VC_OCCLUSION_PIXEL_RESTORE_matte_span_0001_v3_sub_0052"
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
V1 = _load("vc_final_occlusion_v1_for_v3", HERE / "final_occlusion_composition_v1.py")
V2 = _load("vc_final_occlusion_v2_for_v3", HERE / "final_occlusion_composition_v2.py")
base = V1.base
full = V1.full
LEGACY = V2.LEGACY
GLYPH = V2.GLYPH

OCCLUSION_NAMES = {OLD_MATTE_NAME, V2_MATTE_NAME, NEW_MATTE_NAME}


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
    v3 = item_inventory(timeline, NEW_MATTE_NAME)
    ok = bool(
        len(old) == 1
        and [old[0].get("start"), old[0].get("end")] == list(OLD_MATTE_RANGE)
        and int(old[0].get("duration") or -1) == OLD_MATTE_RANGE[1] - OLD_MATTE_RANGE[0]
        and not v2
        and not v3
    )
    return {"old": old, "v2": v2, "v3": v3, "ok": ok}


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
    if [summary.get("start"), summary.get("end")] != list(OLD_MATTE_RANGE):
        return {"ok": False, "error": "old_matte_range", "summary": summary}
    deletion = base.delete_items(timeline, [rows[0][1]])
    time.sleep(0.15)
    remaining = item_inventory(timeline, OLD_MATTE_NAME)
    return {"ok": bool(deletion.get("ok") and not remaining), "deletion": deletion, "remaining": remaining, "summary": summary}


def _select_png_rgb8(project: Any) -> Dict[str, Any]:
    formats = base.safe_value(project, "GetRenderFormats", default={})
    if not isinstance(formats, Mapping):
        raise RuntimeError("render_formats")
    candidates = []
    for render_format, extension in formats.items():
        if str(extension).lower().lstrip(".") != "png":
            continue
        codecs = base.safe_value(project, "GetRenderCodecs", str(render_format), default={})
        if not isinstance(codecs, Mapping):
            continue
        for description, value in codecs.items():
            text = f"{description} {value}".lower()
            score = 0
            if str(value).upper() == "RGB8": score += 1000
            if "rgb" in text: score += 100
            if "8 bit" in text or "8-bit" in text or "rgb8" in text: score += 200
            if "rgba" in text: score -= 20
            candidates.append({"format": str(render_format), "extension": "png", "codec_description": str(description), "codec": str(value), "score": score})
    candidates.sort(key=lambda row: (-int(row["score"]), row["format"], row["codec_description"]))
    if not candidates or int(candidates[0]["score"]) < 200:
        raise RuntimeError(f"png_rgb8_unavailable:{candidates}")
    return {"selection": candidates[0], "candidates": candidates, "ok": True}


def _render(project: Any, timeline: Any, output_dir: Path, name: str, selection: Mapping[str, Any], dimensions: Mapping[str, Any]) -> Dict[str, Any]:
    # V2's renderer already enforces exactly frames 426..453 and removes jobs.
    return V2._render_sequence(project, timeline, output_dir, name, selection, dimensions)


def _capture_render_session(resolve: Any, project: Any) -> Dict[str, Any]:
    current = base.safe_value(project, "GetCurrentRenderFormatAndCodec", default={})
    return {
        "page": str(base.safe_value(resolve, "GetCurrentPage", default="") or ""),
        "timeline": base.safe_value(project, "GetCurrentTimeline", default=None),
        "format": current.get("format") if isinstance(current, Mapping) else None,
        "codec": current.get("codec") if isinstance(current, Mapping) else None,
        "mode": base.as_int(base.safe_value(project, "GetCurrentRenderMode", default=1), 1),
    }


def _restore_render_session(resolve: Any, project: Any, session: Mapping[str, Any]) -> Dict[str, Any]:
    rows = []
    if session.get("timeline") is not None:
        value, call = base.direct_call(project, "SetCurrentTimeline", session["timeline"]); rows.append({"name": "timeline", "ok": bool(value), "call": call})
    if session.get("format") and session.get("codec"):
        value, call = base.direct_call(project, "SetCurrentRenderFormatAndCodec", str(session["format"]), str(session["codec"])); rows.append({"name": "format", "ok": bool(value), "call": call})
    value, call = base.direct_call(project, "SetCurrentRenderMode", int(session.get("mode") or 1)); rows.append({"name": "mode", "ok": bool(value), "call": call})
    value, call = base.direct_call(project, "SetRenderSettings", {"SelectAllFrames": True}); rows.append({"name": "settings", "ok": bool(value), "call": call})
    if session.get("page"):
        value, call = base.direct_call(resolve, "OpenPage", str(session["page"])); rows.append({"name": "page", "ok": bool(value), "call": call})
    return {"rows": rows, "ok": bool(rows and all(row["ok"] for row in rows))}


def _helper_command(root: Path, report_dir: Path, command: Mapping[str, Any]) -> list[str]:
    python_exe = str(((command.get("occlusion") or {}).get("external_python") or ""))
    if not python_exe:
        raise RuntimeError("external_python")
    return [
        python_exe,
        str((root / HELPER_RELATIVE_PATH).resolve()),
        "--source-video", str((root / SOURCE_VIDEO_RELATIVE).resolve()),
        "--with-come-dir", str((report_dir / "render_with_come_no_oldmatte").resolve()),
        "--without-come-dir", str((report_dir / "render_without_come_no_oldmatte").resolve()),
        "--anchor-mask-dir", str((root / ANCHOR_DIR_RELATIVE).resolve()),
        "--output-root", str((report_dir / "generated_pixel_restore_v3").resolve()),
    ]


def _run_helper(root: Path, report_dir: Path, command: Mapping[str, Any]) -> Dict[str, Any]:
    argv = _helper_command(root, report_dir, command)
    started = base.utc_now()
    process = subprocess.run(argv, cwd=str(root), text=True, capture_output=True, timeout=300, check=False)
    result = {
        "argv": argv,
        "started_at": started,
        "finished_at": base.utc_now(),
        "returncode": process.returncode,
        "stdout": process.stdout[-20000:],
        "stderr": process.stderr[-20000:],
        "ok": process.returncode == 0,
    }
    base.write_json(report_dir / "pixel_restore_helper_invocation.json", result)
    if not result["ok"]:
        raise RuntimeError(f"pixel_restore_helper:{process.returncode}:{process.stderr[-500:]}")
    manifest_path = report_dir / "generated_pixel_restore_v3" / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("pixel_restore_manifest_missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("task_id") != TASK_ID or manifest.get("ok") is not True or manifest.get("rgb_authority") != "resolve_render_with_target_come_disabled":
        raise RuntimeError("pixel_restore_manifest_contract")
    result["manifest"] = manifest
    return result


def _legacy_args() -> SimpleNamespace:
    return SimpleNamespace(
        caption_occlusion_reuse_media_pool_items=True,
        caption_occlusion_set_straight_alpha=True,
        caption_occlusion_alpha_mode="Straight",
        caption_occlusion_verify_settle_timeout_sec=1.5,
        caption_occlusion_verify_poll_interval_sec=0.1,
    )


def verify_v3_occlusion(timeline: Any) -> Dict[str, Any]:
    old = item_inventory(timeline, OLD_MATTE_NAME)
    v2 = item_inventory(timeline, V2_MATTE_NAME)
    rows = item_inventory(timeline, NEW_MATTE_NAME)
    max_caption = V1.caption_track_max(timeline)
    ok = bool(
        not old and not v2 and len(rows) == 1
        and [rows[0].get("start"), rows[0].get("end")] == list(TARGET_RANGE)
        and int(rows[0].get("duration") or -1) == TARGET_DURATION
        and int(rows[0].get("track_index") or 0) > max_caption
        and str(rows[0].get("media_pool_item_name") or "") == NEW_MATTE_NAME
    )
    return {"old": old, "v2": v2, "rows": rows, "max_caption_track": max_caption, "ok": ok}


def _span(report_dir: Path) -> Dict[str, Any]:
    rgba_dir = report_dir / "generated_pixel_restore_v3" / "rgba"
    return {
        "span_id": "matte_span_0001_pixel_restore_v3",
        "item_name": NEW_MATTE_NAME,
        "timeline_frame_start": TARGET_RANGE[0],
        "timeline_frame_end_exclusive": TARGET_RANGE[1],
        "duration_frames": TARGET_DURATION,
        "rgba_pattern": str((rgba_dir / "rgba_%06d.png").resolve()),
        "first_rgba_file": str((rgba_dir / f"rgba_{TARGET_RANGE[0]:06d}.png").resolve()),
        "canonical_cue_ids": ["sub_0052"],
    }


def ensure_v3_occlusion(project: Any, timeline: Any, report_dir: Path) -> Dict[str, Any]:
    existing = verify_v3_occlusion(timeline)
    if existing["ok"]:
        return {"ok": True, "mutated": False, "idempotent_noop": True, "verification": existing}
    preimage = verify_source_preimage(timeline)
    if not preimage["ok"]:
        return {"ok": False, "mutated": False, "error": "v3_preimage", "preimage": preimage}
    old_item = next(item for _track, item in base.all_video_items(timeline) if base.item_name(item) == OLD_MATTE_NAME)
    target_track = V1.caption_track_max(timeline) + 1
    track_setup = base.ensure_video_tracks(timeline, target_track)
    if not track_setup.get("ok"):
        return {"ok": False, "mutated": False, "error": "track_setup", "track_setup": track_setup}
    span = _span(report_dir)
    imported = LEGACY._import_rgba_sequence_media_pool(project, span, _legacy_args(), 24.0)
    media_item = imported.get("item")
    if not imported.get("ok") or media_item is None:
        return {"ok": False, "mutated": False, "error": "rgba_import", "import": base.json_safe({k: v for k, v in imported.items() if k != "item"})}
    properties = imported.get("properties") if isinstance(imported.get("properties"), Mapping) else {}
    if str(properties.get("Input Color Space") or "") not in {"Project", ""}:
        return {"ok": False, "mutated": False, "error": "rgba_input_color_space", "properties": base.json_safe(properties), "imported_media_item": media_item, "imported_new": bool(imported.get("imported"))}
    deletion = base.delete_items(timeline, [old_item])
    time.sleep(0.15)
    if not deletion.get("ok") or item_inventory(timeline, OLD_MATTE_NAME):
        return {"ok": False, "mutated": True, "error": "old_matte_delete", "deletion": deletion, "imported_media_item": media_item, "imported_new": bool(imported.get("imported"))}
    append = LEGACY._append_rgba_sequence_item(project, timeline, media_item, span, target_track, _legacy_args())
    verification = verify_v3_occlusion(timeline)
    return {
        "ok": bool(append.get("ok") and verification.get("ok")),
        "mutated": True,
        "idempotent_noop": False,
        "target_track": target_track,
        "track_setup": track_setup,
        "import": base.json_safe({k: v for k, v in imported.items() if k != "item"}),
        "imported_media_item": media_item,
        "imported_new": bool(imported.get("imported")),
        "deletion": deletion,
        "append": base.json_safe({k: v for k, v in append.items() if k != "item"}),
        "verification": verification,
    }


def _delete_timeline(media_pool: Any, timeline: Any) -> Dict[str, Any]:
    value, call = base.direct_call(media_pool, "DeleteTimelines", [timeline])
    return {"ok": bool(value), "call": call}


def _render_final(resolve: Any, project: Any, target: Any, report_dir: Path, selection: Mapping[str, Any], dimensions: Mapping[str, Any]) -> Dict[str, Any]:
    session = _capture_render_session(resolve, project)
    opened, call = base.direct_call(resolve, "OpenPage", "deliver")
    if not opened:
        raise RuntimeError("open_deliver_final")
    render = _render(project, target, report_dir / "render_target_occlusion_v3", "target_occlusion_v3_", selection, dimensions)
    restore = _restore_render_session(resolve, project, session)
    return {"render": render, "restore": restore, "open_call": call, "ok": bool(render.get("ok") and restore.get("ok"))}


def cleanup_before_save(project_manager: Any, project: Any, media_pool: Any, source: Any, temp_name: str, target_created: bool, imported_media_item: Any, imported_new: bool) -> Dict[str, Any]:
    result: Dict[str, Any] = {"errors": [], "save_call_count": 0}
    try:
        if source is not None:
            selected, call = base.direct_call(project, "SetCurrentTimeline", source); result["restore_source"] = call
            if not selected: result["errors"].append("restore_source")
        temp = base.find_timeline(project, temp_name)
        if temp is not None:
            deletion = _delete_timeline(media_pool, temp); result["delete_temp"] = deletion
            if not deletion["ok"]: result["errors"].append("delete_temp")
        target = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target_created and target is not None:
            deletion = _delete_timeline(media_pool, target); result["delete_target"] = deletion
            if not deletion["ok"]: result["errors"].append("delete_target")
        if imported_new and imported_media_item is not None:
            deletion = LEGACY._delete_media_pool_items(project, [imported_media_item]); result["delete_imported_media"] = base.json_safe(deletion)
            if not deletion.get("ok"): result["errors"].append("delete_imported_media")
        save = base.save_project(project_manager); result["save"] = save; result["save_call_count"] = 1
        if not save.get("success"): result["errors"].append("save_cleanup")
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
    if not run_id or command.get("task_id") != TASK_ID or command.get("mode") != MODE:
        raise ValueError("command_identity")
    report_dir = base.relative_path(root, command.get("artifacts_dir")); report_dir.mkdir(parents=True, exist_ok=True)
    temp_name = f"{TEMP_TIMELINE_PREFIX}{run_id[-12:]}"
    report: Dict[str, Any] = {
        "schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "mode": MODE, "ok": False,
        "source_timeline_name": SOURCE_TIMELINE_NAME, "target_timeline_name": TARGET_TIMELINE_NAME,
        "caption_mutation_count": 0, "temporary_caption_toggle_count": 0, "occlusion_mutation_count": 0,
        "save_call_count": 0, "resolve_invocation_contract": 1, "visual_approval_required": True,
        "further_rollout_authorized": False, "started_at": base.utc_now(), "failures": [],
    }
    project_manager = project = media_pool = source = None
    temp = None
    target_created = False
    imported_media_item = None
    imported_new = False
    saved = False
    try:
        source_contract = base.verify_source_contract(root, command); base.write_json(report_dir / "source_contract_verification.json", source_contract)
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
            if not matched: raise RuntimeError(f"anchor_hash:{frame}")
        base.write_json(report_dir / "clean_person_anchor_verification.json", {"rows": anchor_rows, "ok": True})

        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None: raise RuntimeError("source_timeline")
        for forbidden in (TARGET_TIMELINE_NAME,):
            if base.find_timeline(project, forbidden) is not None: raise RuntimeError(f"target_exists:{forbidden}")
        source_uid = base.timeline_unique_id(source)
        source_caption_before = V1.caption_snapshot(source)
        source_full_before = V1.stable_inventory(source)
        source_nonocc_before = stable_inventory_without_occlusion(source)
        source_preimage = verify_source_preimage(source)
        if not source_preimage["ok"]: raise RuntimeError("source_preimage")
        if full.track_two_item_names(source): raise RuntimeError("source_v2_not_empty")
        _find_caption(source)
        base.write_json(report_dir / "occlusion_v3_preflight.json", {
            "resolve_calls": resolve_calls, "source_unique_id": source_uid, "source_caption_snapshot": source_caption_before,
            "source_preimage": source_preimage, "source_non_occlusion_inventory": source_nonocc_before,
            "rejected_timelines_never_source": [REJECTED_V1_TIMELINE_NAME, REJECTED_V2_TIMELINE_NAME], "ok": True,
        })

        # Disposable exact-render authority timeline.
        temp_value, temp_call = base.direct_call(source, "DuplicateTimeline", temp_name)
        temp = temp_value if temp_value is not None else base.find_timeline(project, temp_name)
        if temp is None: raise RuntimeError("duplicate_temp")
        if not V1.caption_snapshots_equal(source_caption_before, V1.caption_snapshot(temp)): raise RuntimeError("temp_duplicate_caption_regression")
        removed = _remove_old_matte(temp)
        if not removed.get("ok"): raise RuntimeError("temp_remove_old_matte")
        if stable_inventory_without_occlusion(temp) != source_nonocc_before: raise RuntimeError("temp_nonocc_regression")

        dimensions = GLYPH.timeline_dimensions(temp, project)
        if int(dimensions.get("width") or 0) != 1080 or int(dimensions.get("height") or 0) != 1920 or abs(float(dimensions.get("frame_rate") or 0) - 24.0) > 0.001:
            raise RuntimeError(f"render_dimensions:{dimensions}")
        render_capability = _select_png_rgb8(project)
        selection = render_capability["selection"]
        session = _capture_render_session(resolve, project)
        opened, open_call = base.direct_call(resolve, "OpenPage", "deliver")
        if not opened: raise RuntimeError("open_deliver")
        with_render = _render(project, temp, report_dir / "render_with_come_no_oldmatte", "with_come_no_oldmatte_", selection, dimensions)
        if not with_render.get("ok"): raise RuntimeError("with_come_render")
        _track, target_caption = _find_caption(temp)
        before_enabled = base.safe_value(target_caption, "GetClipEnabled", default=None)
        value, toggle_call = base.direct_call(target_caption, "SetClipEnabled", False)
        after_enabled = base.safe_value(target_caption, "GetClipEnabled", default=None)
        if value is False or before_enabled is False or after_enabled is not False: raise RuntimeError("temporary_caption_disable")
        report["temporary_caption_toggle_count"] = 1
        without_render = _render(project, temp, report_dir / "render_without_come_no_oldmatte", "without_come_no_oldmatte_", selection, dimensions)
        if not without_render.get("ok"): raise RuntimeError("without_come_render")
        restore = _restore_render_session(resolve, project, session)
        if not restore.get("ok"): raise RuntimeError("restore_render_session")
        base.write_json(report_dir / "render_authority_v3.json", {
            "temporary_timeline": temp_name, "duplicate_call": temp_call, "old_matte_removal": removed,
            "target_caption": TARGET_CAPTION_NAME, "temporary_toggle_call": toggle_call,
            "temporary_toggle_before": base.json_safe(before_enabled), "temporary_toggle_after": base.json_safe(after_enabled),
            "render_capability": render_capability, "dimensions": dimensions, "open_deliver_call": open_call,
            "with_come": with_render, "without_come": without_render, "restore": restore,
            "rgb_authority": "resolve_render_with_target_come_disabled", "ok": True,
        })

        helper = _run_helper(root, report_dir, command)
        # Delete the disposable timeline before constructing the persistent target.
        selected_source, select_source_call = base.direct_call(project, "SetCurrentTimeline", source)
        if not selected_source: raise RuntimeError("restore_source_before_temp_delete")
        temp_delete = _delete_timeline(media_pool, temp)
        if not temp_delete["ok"] or base.find_timeline(project, temp_name) is not None: raise RuntimeError("delete_temp")
        temp = None

        duplicate_value, duplicate_call = base.direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
        target = duplicate_value if duplicate_value is not None else base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target is None: raise RuntimeError("duplicate_target")
        target_created = True
        selected_target, select_target_call = base.direct_call(project, "SetCurrentTimeline", target)
        if not selected_target: raise RuntimeError("select_target")
        target_caption_duplicate = V1.caption_snapshot(target)
        if not V1.caption_snapshots_equal(source_caption_before, target_caption_duplicate): raise RuntimeError("target_duplicate_caption_regression")
        if stable_inventory_without_occlusion(target) != source_nonocc_before: raise RuntimeError("target_duplicate_nonocc_regression")

        first = ensure_v3_occlusion(project, target, report_dir)
        imported_media_item = first.get("imported_media_item"); imported_new = bool(first.get("imported_new"))
        after_first_caption = V1.caption_snapshot(target)
        first_caption_ok = V1.caption_snapshots_equal(target_caption_duplicate, after_first_caption)
        first_nonocc_ok = stable_inventory_without_occlusion(target) == source_nonocc_before
        if not first.get("ok") or not first.get("mutated") or not first_caption_ok or not first_nonocc_ok: raise RuntimeError("v3_first_application")
        second = ensure_v3_occlusion(project, target, report_dir)
        after_second_caption = V1.caption_snapshot(target)
        second_caption_ok = V1.caption_snapshots_equal(after_first_caption, after_second_caption)
        second_nonocc_ok = stable_inventory_without_occlusion(target) == source_nonocc_before
        if not second.get("ok") or second.get("mutated") or second.get("idempotent_noop") is not True or not second_caption_ok or not second_nonocc_ok: raise RuntimeError("v3_idempotency")
        pre_save = verify_v3_occlusion(target)
        if not pre_save["ok"]: raise RuntimeError("v3_pre_save")
        base.write_json(report_dir / "occlusion_v3_application.json", {
            "select_source_call": select_source_call, "temp_delete": temp_delete, "duplicate_target_call": duplicate_call,
            "select_target_call": select_target_call, "helper_manifest": helper["manifest"],
            "first_application": base.json_safe({k: v for k, v in first.items() if k != "imported_media_item"}),
            "second_application": base.json_safe({k: v for k, v in second.items() if k != "imported_media_item"}),
            "checks": {"caption_unchanged_after_first": first_caption_ok, "caption_unchanged_after_second": second_caption_ok,
                       "non_occlusion_inventory_after_first": first_nonocc_ok, "non_occlusion_inventory_after_second": second_nonocc_ok,
                       "idempotent_second_noop": second.get("idempotent_noop") is True and second.get("mutated") is False,
                       "v3_matte_exact": pre_save["ok"]},
            "caption_snapshot_before": target_caption_duplicate, "caption_snapshot_after": after_second_caption, "ok": True,
        })

        final_render = _render_final(resolve, project, target, report_dir, selection, dimensions)
        base.write_json(report_dir / "final_render_v3.json", final_render)
        if not final_render.get("ok"): raise RuntimeError("final_render_v3")

        save = base.save_project(project_manager); report["save_call_count"] = 1; saved = True
        if not save.get("success"): raise RuntimeError("save")
        project_manager, project, media_pool, reacquire_calls = base.get_project(resolve)
        source_after = base.find_timeline(project, SOURCE_TIMELINE_NAME); target_after = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if source_after is None or target_after is None: raise RuntimeError("reacquire")
        source_caption_after = V1.caption_snapshot(source_after); target_caption_persistent = V1.caption_snapshot(target_after)
        target_occ = verify_v3_occlusion(target_after)
        checks = {
            "source_unique_id_unchanged": base.timeline_unique_id(source_after) == source_uid,
            "source_full_inventory_unchanged": V1.stable_inventory(source_after) == source_full_before,
            "source_caption_unchanged": V1.caption_snapshots_equal(source_caption_before, source_caption_after),
            "target_caption_unchanged": V1.caption_snapshots_equal(source_caption_before, target_caption_persistent),
            "target_non_occlusion_inventory_unchanged": stable_inventory_without_occlusion(target_after) == source_nonocc_before,
            "target_v3_occlusion_exact": target_occ["ok"], "textplus_114": target_caption_persistent["count"] == EXPECTED_TEXTPLUS_COUNT,
            "v2_track_empty": not full.track_two_item_names(target_after), "temp_deleted": base.find_timeline(project, temp_name) is None,
            "one_save": report["save_call_count"] == 1, "idempotency_pre_save": second.get("idempotent_noop") is True and second.get("mutated") is False,
            "helper_manifest_ok": helper["manifest"].get("ok") is True, "final_render_generated": final_render.get("ok") is True,
        }
        persistent = {"schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "reacquire_calls": reacquire_calls, "save": save,
                      "source_caption_snapshot_before": source_caption_before, "source_caption_snapshot_after": source_caption_after,
                      "target_caption_snapshot": target_caption_persistent, "occlusion": target_occ, "checks": checks,
                      "visual_approval_required": True, "further_rollout_authorized": False, "ok": all(checks.values())}
        base.write_json(report_dir / "persistent_readback.json", persistent)
        if not persistent["ok"]: raise RuntimeError("persistent_readback")
        report.update({"ok": True, "final_textplus_count": EXPECTED_TEXTPLUS_COUNT, "caption_mutation_count": 0,
                       "occlusion_mutation_count": 1, "source_timeline_unchanged": True, "caption_baseline_unchanged": True,
                       "persistent_readback_ok": True, "idempotency_ok": True, "pixel_restore_helper_ok": True,
                       "final_render_evidence_generated": True, "occlusion_target_track": int(target_occ["rows"][0]["track_index"]),
                       "target_timeline_kept": True})
        return report
    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc)); report["traceback"] = traceback.format_exc()
        if not saved and project_manager is not None and project is not None and media_pool is not None:
            cleanup = cleanup_before_save(project_manager, project, media_pool, source, temp_name, target_created, imported_media_item, imported_new)
            base.write_json(report_dir / "failure_cleanup.json", cleanup); report["save_call_count"] = int(cleanup.get("save_call_count") or 0); report["failure_cleanup_ok"] = cleanup.get("ok") is True
        elif saved:
            report["post_save_failure_target_retained"] = True; report["manual_delete_required_before_next_task"] = True
        return report
