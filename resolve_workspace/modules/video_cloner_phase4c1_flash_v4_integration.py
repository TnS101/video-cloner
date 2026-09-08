"""Integrate the accepted neutral-RGBA Flash V4 layer on the Phase 4B timeline."""
from __future__ import annotations

import importlib.util
import json
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V4 = _load("vc_accepted_flash_v4_for_phase4c1", HERE / "advanced_transition_flash_neutral_rgba_v4.py")
V1 = V4.V1
P4B = _load("vc_phase4b_for_phase4c1", HERE / "video_cloner_phase4b_timeline_application.py")

TASK_ID = "VIDEO_CLONER_PHASE4C1_ACCEPTED_FLASH_V4_INTEGRATION"
MODE = "phase4c1_apply_accepted_flash_v4"
VERSION = "video_cloner_phase4c1_flash_v4_integration_2"
# Historical exports retained only for the accepted Reel #1 Phase 4C2 module.
# Phase 4C1 validation and execution do not use them.
PROJECT_NAME = "New Project 1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_standalone_timeline"
PROTECTED_TIMELINE_NAME = "DZsqH7auhjt_textplus_full"
PROTECTED_SIGNATURE = "f6612264d0624e53b9674a0d8095df93afc5e3ea3f045446f789633e81203b01"
EXPECTED_FLASH_FRAMES = (96, 377, 426, 454, 758)
EXPECTED_CARRIER_STARTS = (94, 375, 424, 452, 756)
EXPECTED_BASE_CLIPS = 22
EXPECTED_DURATION = 965
EXPECTED_FPS = 24


def validate_plan(plan: Mapping[str, Any]) -> None:
    if plan.get("schema") != "video_cloner.phase4c1_flash_v4_plan" or plan.get("schema_version") != 2:
        raise ValueError("plan_schema")
    if plan.get("task_id") != TASK_ID or plan.get("architecture_family") != V4.ARCHITECTURE_FAMILY:
        raise ValueError("plan_identity")
    target_name = str(plan.get("target_timeline_name") or "")
    artifact = plan.get("artifact") or {}
    if not plan.get("project_name") or not target_name or artifact.get("timeline_name") != target_name:
        raise ValueError("plan_target_identity")
    if plan.get("protected_timeline_name") is not None or plan.get("protected_signature") is not None:
        raise ValueError("plan_legacy_protection")
    if any(type(artifact.get(key)) is not int or artifact[key] <= 0 for key in ("clip_count", "duration_frames")) or artifact.get("fps") != 24 or not artifact.get("fcpxml_sha256"):
        raise ValueError("plan_artifact")
    carrier = plan.get("carrier") or {}
    if carrier != {
        "kind": "transparent_rgba_sequence",
        "asset_dir": V4.NEUTRAL_ASSET_DIR_RELATIVE,
        "pattern": V4.NEUTRAL_PATTERN,
        "frame_count": 4,
        "source_start": 0,
        "source_end_exclusive": 4,
        "media_pool_item_name": V4.NEUTRAL_MEDIA_POOL_ITEM_NAME,
        "png_sha256": V4.NEUTRAL_PNG_SHA256,
        "source_video_pixels_possible": False,
    }:
        raise ValueError("plan_carrier")
    rows = plan.get("flashes")
    if not isinstance(rows, list):
        raise ValueError("plan_flashes")
    seen = set()
    for index, row in enumerate(rows, 1):
        cut = int(row.get("cut_frame") or -1)
        authority = row.get("authority") or {}
        expected = {
            "name": f"VC_FLASH_{index:03d}_frame_{cut:04d}",
            "transition_type": "flash_cut",
            "cut_frame": cut,
            "start_frame": cut - 2,
            "duration_frames": 4,
            "outgoing_frames": 2,
            "incoming_frames": 2,
            "flash_color": [1.0, 1.0, 1.0],
            "alpha_keyframes": [[0, 0.0], [2, 0.75], [3, 0.0]],
            "authority": authority,
        }
        if row != expected or cut in seen or cut < 2 or cut + 2 > artifact["duration_frames"]:
            raise ValueError(f"plan_flash:{index}")
        if authority.get("editor_actionable") is not True or authority.get("confidence") != "high" or (authority.get("placement") is not None and authority.get("placement") != "at_cut"):
            raise ValueError(f"plan_flash_authority:{index}")
        handles = authority.get("handle_check")
        if isinstance(handles, Mapping) and handles.get("ok") is not True:
            raise ValueError(f"plan_flash_handles:{index}")
        seen.add(cut)
    unhashed = dict(plan)
    digest = str(unhashed.pop("plan_sha256", ""))
    if not digest or V1.canonical_sha256(unhashed) != digest:
        raise ValueError("plan_hash")


def find_one(project: Any, name: str) -> Any:
    matches = P4B.find_timelines(project, name)
    if len(matches) != 1:
        raise RuntimeError(f"timeline_identity:{name}:{len(matches)}")
    return matches[0]


def source_rows(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        [dict(row) for row in snapshot.get("video_items", []) if not str(row.get("name") or "").startswith(V1.FLASH_PREFIX)],
        key=lambda row: (row.get("start"), row.get("track_index"), row.get("name")),
    )


def validate_base_geometry(timeline: Any, contract: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = P4B.timeline_snapshot(timeline)
    rows = source_rows(snapshot)
    if len(rows) != len(contract["clips"]) or snapshot.get("audio_items") or any(row.get("track_index") != 1 for row in rows):
        raise RuntimeError("base_track_counts")
    base = int(snapshot.get("start_frame") or 0)
    for expected, actual in zip(contract["clips"], rows):
        if actual.get("start") - base != expected["timeline_start"] or actual.get("duration") != expected["duration"] or actual.get("left_offset") != expected["source_start"]:
            raise RuntimeError(f"base_geometry:{expected['index']}")
        if not actual.get("has_media_pool_item") or not P4B.same_path(actual.get("media_path", ""), contract["source_path"]):
            raise RuntimeError(f"base_media:{expected['index']}")
        if int(actual.get("fusion_comp_count") or 0) != 0:
            raise RuntimeError(f"base_fusion:{expected['index']}")
    if max(row["start"] - base + row["duration"] for row in rows) != contract["duration_frames"]:
        raise RuntimeError("base_duration")
    settings = [value for value in snapshot["settings"].values() if value not in (None, "")]
    if not settings or any(abs(float(value) - contract["fps"]) > 1e-6 for value in settings):
        raise RuntimeError("base_fps")
    signature = V1.canonical_sha256(rows)
    return {"ok": True, "clip_count": len(rows), "duration_frames": contract["duration_frames"], "fps": contract["fps"], "rows": rows, "signature": signature, "snapshot": snapshot}


def non_target_inventory(project: Any, target_name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    inventory = P4B.timeline_inventory(project)
    if sum(row.get("name") == target_name for row in inventory) != 1:
        raise RuntimeError("target_inventory_identity")
    return inventory, [row for row in inventory if row.get("name") != target_name]


def require_same_non_targets(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> None:
    key = lambda row: (row.get("name"), row.get("signature"))
    if Counter(map(key, before)) != Counter(map(key, after)):
        raise RuntimeError("non_target_timeline_changed")


def forbidden_counts(timeline: Any, base: Mapping[str, Any], flash: Mapping[str, Any]) -> dict[str, int]:
    nondefault = retime = base_fusion = 0
    for row in base["rows"]:
        props = row.get("properties") or {}
        for key, default in (("ZoomX", 1.0), ("ZoomY", 1.0), ("PositionX", 0.0), ("PositionY", 0.0), ("RotationAngle", 0.0)):
            if key in props and abs(float(props[key]) - default) > 1e-6:
                nondefault += 1
        if "RetimeSpeed" in props and abs(float(props["RetimeSpeed"]) - 100.0) > 1e-6:
            retime += 1
        base_fusion += int(row.get("fusion_comp_count") or 0)
    return {
        "speed_retime": retime,
        "animated_zoom_transform": nondefault,
        "whip_transitions": 0,
        "slide_transitions": 0,
        "blur_filters": 0,
        "transition_items": 0,
        "caption_title_items": 0,
        "occlusion_components": 0,
        "base_clip_fusion_compositions": base_fusion,
        "source_video_flash_carriers": int(flash.get("source_video_carrier_count") or 0),
    }


def _render_status(status: Any) -> str:
    if isinstance(status, Mapping):
        for key in ("JobStatus", "jobStatus", "Status", "status"):
            if status.get(key) is not None:
                return str(status[key]).strip().lower()
    return ""


def capture_visual_evidence(project: Any, timeline: Any, flashes: list[Mapping[str, Any]], output_dir: Path) -> dict[str, Any]:
    """Render the four frames belonging to every planned carrier."""
    output_dir.mkdir(parents=True, exist_ok=False)
    formats = V1.safe_call(project, "GetRenderFormats", default={}) or {}
    candidates = [(str(fmt), str(ext).lower().lstrip(".")) for fmt, ext in formats.items() if str(ext).lower().lstrip(".") == "png"]
    if not candidates:
        raise RuntimeError("visual_png_format_unavailable")
    render_format, extension = sorted(candidates)[0]
    codecs = V1.safe_call(project, "GetRenderCodecs", render_format, default={}) or {}
    if not codecs:
        raise RuntimeError("visual_png_codec_unavailable")
    codec = str(sorted(codecs.items(), key=lambda row: str(row[0]).lower())[0][1])
    if not V1.safe_call(project, "SetCurrentTimeline", timeline, default=False):
        raise RuntimeError("visual_target_selection")
    if not V1.safe_call(project, "SetCurrentRenderFormatAndCodec", render_format, codec, default=False):
        raise RuntimeError("visual_render_format")
    V1.safe_call(project, "SetCurrentRenderMode", 1, default=False)
    evidence = []
    try:
        for row in flashes:
            cut = int(row["cut_frame"])
            start = int(row["start_frame"])
            frame_dir = output_dir / f"cut_{cut:04d}"
            frame_dir.mkdir()
            settings = {
                "SelectAllFrames": False, "MarkIn": start, "MarkOut": start + 3,
                "TargetDir": str(frame_dir), "CustomName": f"flash_{cut:04d}",
                "UniqueFilenameStyle": 1, "ExportVideo": True, "ExportAudio": False,
                "FormatWidth": 304, "FormatHeight": 540, "FrameRate": 24.0,
                "PixelAspectRatio": "square", "ReplaceExistingFilesInPlace": True,
            }
            if not V1.safe_call(project, "SetRenderSettings", settings, default=False):
                raise RuntimeError(f"visual_render_settings:{cut}")
            job = str(V1.safe_call(project, "AddRenderJob", default="") or "")
            if not job or not V1.safe_call(project, "StartRendering", job, default=False):
                raise RuntimeError(f"visual_render_start:{cut}")
            deadline = time.monotonic() + 180
            terminal = ""
            while time.monotonic() < deadline:
                status = V1.safe_call(project, "GetRenderJobStatus", job, default={})
                terminal = _render_status(status)
                active = bool(V1.safe_call(project, "IsRenderingInProgress", default=False))
                if any(token in terminal for token in ("fail", "cancel", "error")):
                    raise RuntimeError(f"visual_render_failed:{cut}:{terminal}")
                if terminal in {"complete", "completed", "success", "succeeded"} and not active:
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError(f"visual_render_timeout:{cut}")
            files = sorted(path for path in frame_dir.glob(f"*.{extension}") if path.stat().st_size > 0)
            V1.safe_call(project, "DeleteRenderJob", job, default=False)
            if len(files) != 4:
                raise RuntimeError(f"visual_frame_count:{cut}:{len(files)}")
            evidence.append({"cut_frame": cut, "carrier_start": start, "terminal_status": terminal, "files": [str(path) for path in files], "file_count": 4})
    finally:
        V1.safe_call(project, "SetRenderSettings", {"SelectAllFrames": True}, default=False)
    return {"ok": len(evidence) == len(flashes), "kind": "targeted_four_frame_lossless_png_evidence", "final_media_export": False, "total_frames": sum(row["file_count"] for row in evidence), "rows": evidence}


def cleanup_unsaved(timeline: Any, media_pool: Any, assigned: list[tuple[Mapping[str, Any], Any]], media_ownership: Mapping[str, Any] | None, added_track: int | None) -> dict[str, Any]:
    errors = []
    items = [item for _, item in assigned]
    if items and not V1.safe_call(timeline, "DeleteClips", items, False, default=False):
        errors.append("delete_flash_items")
    if added_track and not V1.safe_call(timeline, "DeleteTrack", "video", added_track, default=False):
        errors.append("delete_flash_track")
    media_delete = V4._delete_owned_media_pool_item(media_pool, media_ownership)
    if media_delete.get("attempted") and not media_delete.get("ok"):
        errors.append("delete_neutral_media")
    return {"ok": not errors, "errors": errors, "saved": False, "media_delete": media_delete}


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    command = context.get("command") or {}
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    report: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "run_id": run_id, "mode": MODE, "save_project_count": 0, "failures": []}
    assigned: list[tuple[Mapping[str, Any], Any]] = []
    imported_item = timeline = media_pool = None
    media_ownership = None
    added_track = None
    saved = False
    try:
        if command.get("task") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id:
            raise ValueError("command_identity")
        payload = command.get("payload") or {}
        run_mode = str(payload.get("run_mode") or "")
        if run_mode not in {"apply", "idempotency"}:
            raise ValueError("run_mode")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        report_dir = root / str(payload.get("report_dir") or "")
        report_dir.mkdir(parents=True, exist_ok=True)
        plan_path = Path(str(payload.get("plan_path") or "")).resolve()
        if V4._sha256(plan_path) != payload.get("plan_sha256"):
            raise ValueError("plan_file_hash")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        validate_plan(plan)
        flashes = list(plan["flashes"])
        fcpxml = Path(str(payload.get("fcpxml_path") or "")).resolve()
        fcpxml_hash = P4B.sha256(fcpxml)
        if fcpxml_hash != payload.get("fcpxml_sha256") or fcpxml_hash != plan["artifact"]["fcpxml_sha256"]:
            raise ValueError("fcpxml_hash")
        contract = P4B.parse_fcpxml_contract(fcpxml)
        expected_artifact = {"timeline_name": contract["timeline_name"], "clip_count": len(contract["clips"]), "duration_frames": contract["duration_frames"], "fps": contract["fps"]}
        if any(plan["artifact"].get(key) != value for key, value in expected_artifact.items()):
            raise ValueError("artifact_contract")
        project_name = str(plan["project_name"])
        target_name = str(plan["target_timeline_name"])
        if payload.get("expected_project") != project_name or payload.get("target_timeline_name") != target_name:
            raise ValueError("payload_identity")
        manager = V1.safe_call(resolve, "GetProjectManager", default=None)
        project = V1.safe_call(manager, "GetCurrentProject", default=None)
        if project is None or str(V1.safe_call(project, "GetName", default="") or "") != project_name:
            raise RuntimeError("project_identity")
        media_pool = V1.safe_call(project, "GetMediaPool", default=None)
        timeline = find_one(project, target_name)
        inventory_before, non_target_before = non_target_inventory(project, target_name)
        base_before = validate_base_geometry(timeline, contract)
        existing = V4.neutral_flash_snapshot(timeline, flashes, 2)
        expected_count = len(flashes)
        report.update({"run_mode": run_mode, "project_name": project_name, "target_timeline_name": target_name, "base_before": base_before, "flash_before": existing, "timeline_inventory_before": inventory_before, "non_target_before": non_target_before})
        if not flashes:
            if existing.get("count") or int(base_before["snapshot"]["video_track_count"]) != 1:
                raise RuntimeError("empty_plan_prestate")
            inventory_after, non_target_after = non_target_inventory(project, target_name)
            require_same_non_targets(non_target_before, non_target_after)
            counts = forbidden_counts(timeline, base_before, existing)
            if any(counts.values()):
                raise RuntimeError("empty_plan_regression")
            report.update({"ok": True, "classification": "NO_ACTIONABLE_FLASHES", "created_carriers": 0, "configured_fusion": 0, "media_import_count": 0, "track_add_count": 0, "base_after": base_before, "flash_after": existing, "timeline_inventory_after": inventory_after, "non_target_after": non_target_after, "protected_timeline_unchanged": True, "forbidden_operation_counts": counts, "idempotent": True})
        elif run_mode == "idempotency":
            if not existing.get("ok") or existing.get("count") != expected_count or int(base_before["snapshot"]["video_track_count"]) != 2:
                raise RuntimeError("idempotency_flash_state")
            base_after = validate_base_geometry(timeline, contract)
            inventory_after, non_target_after = non_target_inventory(project, target_name)
            require_same_non_targets(non_target_before, non_target_after)
            counts = forbidden_counts(timeline, base_after, existing)
            if base_after["signature"] != base_before["signature"] or any(counts.values()):
                raise RuntimeError("idempotency_regression")
            report.update({"ok": True, "classification": "ALREADY_VALID_REUSED", "created_carriers": 0, "configured_fusion": 0, "media_import_count": 0, "track_add_count": 0, "base_after": base_after, "flash_after": existing, "timeline_inventory_after": inventory_after, "non_target_after": non_target_after, "protected_timeline_unchanged": True, "forbidden_operation_counts": counts, "idempotent": True})
        else:
            if existing.get("count") != 0 or int(base_before["snapshot"]["video_track_count"]) != 1:
                raise RuntimeError("apply_prestate")
            assets = V4.validate_neutral_assets(root)
            if not assets.get("ok"):
                raise RuntimeError("neutral_assets")
            track = V1.ensure_extra_video_track(timeline, 1)
            if not track.get("ok") or int(track.get("target_track") or 0) != 2:
                raise RuntimeError("flash_track")
            added_track = 2
            imported = V4.import_neutral_carrier(media_pool, root, assets)
            media_ownership = imported
            imported_item = imported.get("item")
            report["media_ownership"] = {key: V1.json_safe(value) for key, value in imported.items() if key != "item"}
            if not imported.get("ok") or imported_item is None:
                raise RuntimeError("neutral_import")
            appended = V1.append_flash_carriers(media_pool, timeline, {"media_pool_item": imported_item, "source_start": 0}, flashes, 2)
            assigned = list(appended.get("assigned") or [])
            if not appended.get("ok"):
                raise RuntimeError("flash_append")
            configured = []
            for index, (spec, item) in enumerate(assigned, 1):
                row = V1.configure_flash(item, spec, index)
                configured.append(row)
                if not row.get("ok"):
                    raise RuntimeError(f"flash_configure:{index}")
            flash = V4.neutral_flash_snapshot(timeline, flashes, 2)
            base_after = validate_base_geometry(timeline, contract)
            inventory_after, non_target_after = non_target_inventory(project, target_name)
            require_same_non_targets(non_target_before, non_target_after)
            counts = forbidden_counts(timeline, base_after, flash)
            if not flash.get("ok") or flash.get("neutral_carrier_count") != expected_count or base_after["signature"] != base_before["signature"] or any(counts.values()):
                raise RuntimeError("pre_save_validation")
            visual = capture_visual_evidence(project, timeline, flashes, report_dir / "visual_evidence")
            if not visual.get("ok") or visual.get("total_frames") != expected_count * 4:
                raise RuntimeError("visual_evidence")
            if not V1.safe_call(manager, "SaveProject", default=False):
                raise RuntimeError("save_project")
            report["save_project_count"] = 1
            saved = True
            persistent_flash = V4.neutral_flash_snapshot(timeline, flashes, 2)
            persistent_base = validate_base_geometry(timeline, contract)
            persistent_inventory, persistent_non_targets = non_target_inventory(project, target_name)
            require_same_non_targets(non_target_before, persistent_non_targets)
            if not persistent_flash.get("ok") or persistent_base["signature"] != base_before["signature"]:
                raise RuntimeError("persistent_readback")
            alpha_checks = sum(len(row.get("fusion", {}).get("alpha_keyframes", [])) for row in persistent_flash.get("rows", []))
            report.update({"ok": True, "classification": "FLASH_V4_APPLIED", "created_carriers": expected_count, "configured_fusion": len(configured), "alpha_readback_checks": alpha_checks, "media_import_count": int(imported.get("import_performed") is True), "track_add_count": 1, "neutral_asset_verification": assets, "append": {k: V1.json_safe(v) for k, v in appended.items() if k != "assigned"}, "configure_rows": V1.json_safe(configured), "base_after": persistent_base, "flash_after": persistent_flash, "timeline_inventory_after": persistent_inventory, "non_target_after": persistent_non_targets, "protected_timeline_unchanged": True, "forbidden_operation_counts": counts, "visual_evidence": visual, "persistent_readback_ok": True})
        P4B.write_json(report_dir / "phase4c1_flash_result.json", report)
        return report
    except BaseException as exc:
        report["failures"] = [f"{type(exc).__name__}: {exc}"]
        report["traceback"] = traceback.format_exc()
        if not saved and timeline is not None and media_pool is not None and (assigned or media_ownership is not None or added_track is not None):
            report["rollback"] = cleanup_unsaved(timeline, media_pool, assigned, media_ownership, added_track)
        try:
            root = Path(str((command.get("payload") or {}).get("repository_root") or "")).resolve()
            report_dir = root / str((command.get("payload") or {}).get("report_dir") or "")
            P4B.write_json(report_dir / "phase4c1_flash_result.json", report)
        except Exception:
            pass
        return report
