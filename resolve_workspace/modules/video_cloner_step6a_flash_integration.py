"""Apply the one accepted Reel #2 flash to a derivative of the GOLD timeline.

This module is intentionally an adapter.  Flash media ownership, carrier append,
Fusion construction and Flash readback remain owned by the accepted V4 helpers.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
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


V4 = _load("vc_step6a_accepted_flash_v4", HERE / "advanced_transition_flash_neutral_rgba_v4.py")
V1 = V4.V1
P4B = _load("vc_step6a_phase4b_inventory", HERE / "video_cloner_phase4b_timeline_application.py")
SNAP = _load("vc_step6a_caption_snapshot", HERE / "final_occlusion_composition_v1.py")
C1 = _load("vc_step6a_accepted_phase4c1", HERE / "video_cloner_phase4c1_flash_v4_integration.py")

TASK_ID = "VIDEO_CLONER_STEP6A_GOLD_FLASH_INTEGRATION_V1"
MODE = "step6a_apply_gold_flash"
VERSION = "video_cloner_step6a_flash_integration_1"
PROJECT_NAME = "New Project 1"
GOLD_TIMELINE_NAME = "VIDEO_CLONER_STEP5B_V33_BOUNDED_CLEANUP_GENERATED_ONLY_99830db16b49"
TARGET_TIMELINE_NAME = "VIDEO_CLONER_REEL2_STEP6A_FLASH_V1"
GOLD_DRT_RELATIVE = ".agent/gold/video_cloner/reel2/captions/VIDEO_CLONER_REEL2_CAPTIONS_GOLD_HUMAN_ACCEPTED.drt"
GOLD_DRT_SHA256 = "99b11b92d55c40682f630fd4c52072e006c7e0b6494aef367bda175fb9d4af2e"
AUTHORITY_DIR_RELATIVE = "data/DcJRJtUKScu/accepted/step6a"
DETECTOR_RELATIVE = AUTHORITY_DIR_RELATIVE + "/DcJRJtUKScu_transitions.json"
PLANNING_RELATIVE = AUTHORITY_DIR_RELATIVE + "/DcJRJtUKScu_generic_edit_commands.json"
DETECTOR_SHA256 = "ec459a99b4a2462436310738ae51072f014733d0ee706fa1363b067c2d83817c"
PLANNING_SHA256 = "8529887a3c6182c031b9388f8ea7182c6a1fb4aefd65e13b54b442d3e21efc5e"
EXPECTED_FPS = 24.0
REEL_START = 594
REEL_CUT = 596
REEL_END = 598
FLASH_PREFIX = "VC_FLASH_"
CAPTION_PREFIXES = ("VC5A33::", "VC5A33R::")


class FrameMappingError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_exact(project: Any, name: str, *, allow_missing: bool = False) -> Any:
    matches = P4B.find_timelines(project, name)
    if allow_missing and not matches:
        return None
    if len(matches) != 1:
        raise RuntimeError(f"timeline_identity:{name}:{len(matches)}")
    return matches[0]


def timeline_uid(timeline: Any) -> str:
    return str(V1.safe_call(timeline, "GetUniqueId", default="") or "")


def same_timeline(left: Any, right: Any) -> bool:
    if left is right and left is not None:
        return True
    left_uid, right_uid = timeline_uid(left), timeline_uid(right)
    return bool(left_uid and left_uid == right_uid and V1.timeline_name(left) == V1.timeline_name(right))


def select_and_prove(project: Any, timeline: Any) -> dict[str, Any]:
    selected, call = V1.direct_call(project, "SetCurrentTimeline", timeline)
    readback = V1.safe_call(project, "GetCurrentTimeline", default=None)
    ok = bool(selected and same_timeline(timeline, readback))
    return {"ok": ok, "call": call, "expected_name": V1.timeline_name(timeline), "readback_name": V1.timeline_name(readback), "expected_uid": timeline_uid(timeline), "readback_uid": timeline_uid(readback)}


def verify_input_hashes(root: Path) -> dict[str, Any]:
    rows = []
    for relative, expected in ((GOLD_DRT_RELATIVE, GOLD_DRT_SHA256), (DETECTOR_RELATIVE, DETECTOR_SHA256), (PLANNING_RELATIVE, PLANNING_SHA256)):
        path = root / relative
        actual = sha256(path) if path.is_file() else ""
        rows.append({"path": relative, "expected_sha256": expected, "actual_sha256": actual, "ok": actual == expected})
    return {"ok": all(row["ok"] for row in rows), "rows": rows}


def validate_plan(plan: Mapping[str, Any]) -> None:
    if plan.get("schema") != "video_cloner.step6a_gold_flash_plan" or plan.get("schema_version") != 1 or plan.get("task_id") != TASK_ID:
        raise ValueError("plan_identity")
    if plan.get("project_name") != PROJECT_NAME:
        raise ValueError("plan_project")
    if plan.get("gold_timeline_name") != GOLD_TIMELINE_NAME or plan.get("target_timeline_name") != TARGET_TIMELINE_NAME:
        raise ValueError("plan_timeline")
    if plan.get("gold_drt_sha256") != GOLD_DRT_SHA256 or plan.get("detector_sha256") != DETECTOR_SHA256 or plan.get("planning_sha256") != PLANNING_SHA256:
        raise ValueError("plan_authority_hash")
    mapping = plan.get("reel_mapping") or {}
    if mapping != {"fps": 24, "start_frame": REEL_START, "cut_frame": REEL_CUT, "end_frame_exclusive": REEL_END, "duration_frames": 4}:
        raise ValueError("plan_mapping")
    rows = plan.get("flashes")
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("plan_flash_count")
    row = rows[0]
    if row.get("transition_type") != "flash_cut" or row.get("confidence") != "high" or row.get("editor_actionable") is not True:
        raise ValueError("plan_flash_authority")
    if [int(row.get(key, -1)) for key in ("start_frame", "cut_frame", "end_frame_exclusive", "duration_frames")] != [594, 596, 598, 4]:
        raise ValueError("plan_flash_geometry")
    unhashed = dict(plan)
    digest = str(unhashed.pop("plan_sha256", ""))
    if not digest or V1.canonical_sha256(unhashed) != digest:
        raise ValueError("plan_hash")


def frame_mapping(timeline: Any) -> dict[str, Any]:
    snap = P4B.timeline_snapshot(timeline)
    fps_values = [float(value) for value in snap["settings"].values() if value not in (None, "")]
    start = int(snap.get("start_frame") or 0)
    end = snap.get("end_frame")
    if end is None:
        raise FrameMappingError("STEP6A_GOLD_FRAME_MAPPING_MISMATCH:end_frame_missing")
    end = int(end)
    duration = end - start
    if not fps_values or any(abs(value - EXPECTED_FPS) > 1e-6 for value in fps_values):
        raise FrameMappingError(f"STEP6A_GOLD_FRAME_MAPPING_MISMATCH:fps:{fps_values}")
    mapped = {str(frame): start + frame for frame in (REEL_START, REEL_CUT, REEL_END)}
    if duration < REEL_END or mapped[str(REEL_START)] < start or mapped[str(REEL_END)] > end:
        raise FrameMappingError(f"STEP6A_GOLD_FRAME_MAPPING_MISMATCH:range:{start}:{end}:{duration}")
    return {"ok": True, "fps": EXPECTED_FPS, "timeline_start_frame": start, "timeline_end_frame_exclusive": end, "timeline_duration_frames": duration, "coordinate_system": "reel_relative_plus_timeline_start", "mapped_frames": mapped, "mapped_span": [mapped[str(REEL_START)], mapped[str(REEL_END)]]}


def _caption_items(timeline: Any) -> list[tuple[int, Any]]:
    rows = [(track, item) for track, item in V1.all_video_items(timeline) if V1.item_name(item).startswith(CAPTION_PREFIXES)]
    return sorted(rows, key=lambda pair: (pair[0], V1.item_start(pair[1]), V1.item_name(pair[1])))


def caption_snapshot(timeline: Any) -> dict[str, Any]:
    rows = []
    for track, item in _caption_items(timeline):
        summary = SNAP.base.item_summary(track, item)
        comp = SNAP.base.get_comp(item)
        tool = SNAP.base.get_text_tool(comp)
        if comp is None or tool is None:
            raise RuntimeError(f"caption_text_tool:{V1.item_name(item)}")
        duration = int(summary.get("duration") or 0)
        if duration <= 0:
            raise RuntimeError(f"caption_duration:{V1.item_name(item)}")
        rows.append({
            "name": V1.item_name(item),
            "summary": {field: summary.get(field) for field in SNAP.STABLE_INVENTORY_FIELDS},
            "clip_enabled": SNAP._normalized(SNAP.base.safe_value(item, "GetClipEnabled", default=None)),
            "properties": {name: SNAP._property_snapshot(tool, name, duration) for name in SNAP.CAPTION_PROPERTIES},
        })
    names = [row["name"] for row in rows]
    if not rows or len(names) != len(set(names)):
        raise RuntimeError("caption_identity")
    return {"count": len(rows), "names": names, "rows": rows, "sha256": V1.canonical_sha256(rows)}


def non_caption_snapshot(timeline: Any) -> dict[str, Any]:
    rows = []
    for track, item in V1.all_video_items(timeline):
        name = V1.item_name(item)
        if name.startswith(CAPTION_PREFIXES) or name.startswith(FLASH_PREFIX):
            continue
        rows.append(P4B.item_snapshot(item, track))
    rows.sort(key=lambda row: (row.get("track_index"), row.get("start"), row.get("name")))
    return {"count": len(rows), "rows": rows, "sha256": V1.canonical_sha256(rows)}


def source_state(timeline: Any) -> dict[str, Any]:
    geometry = frame_mapping(timeline)
    return {"timeline_name": V1.timeline_name(timeline), "timeline_uid": timeline_uid(timeline), "video_track_count": V1.track_count(timeline, "video"), "audio_track_count": V1.track_count(timeline, "audio"), "geometry": geometry, "captions": caption_snapshot(timeline), "non_caption": non_caption_snapshot(timeline)}


def source_unchanged(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    return all(before.get(key) == after.get(key) for key in ("timeline_name", "timeline_uid", "video_track_count", "audio_track_count", "geometry", "captions", "non_caption"))


def mapped_flash(mapping: Mapping[str, Any]) -> list[dict[str, Any]]:
    mapped = mapping["mapped_frames"]
    return [{"name": "VC_FLASH_001_frame_0596", "transition_type": "flash_cut", "cut_frame": int(mapped[str(REEL_CUT)]), "start_frame": int(mapped[str(REEL_START)]), "duration_frames": 4, "outgoing_frames": 2, "incoming_frames": 2, "flash_color": [1.0, 1.0, 1.0], "alpha_keyframes": [[0, 0.0], [2, 0.75], [3, 0.0]]}]


def target_contract(source: Mapping[str, Any], target: Any, flashes: list[Mapping[str, Any]]) -> dict[str, Any]:
    captions = caption_snapshot(target)
    non_caption = non_caption_snapshot(target)
    geometry = frame_mapping(target)
    expected_track = int(source["video_track_count"]) + 1
    flash = V4.neutral_flash_snapshot(target, flashes, expected_track)
    checks = {
        "caption_structural_snapshot_unchanged": captions == source["captions"],
        "non_caption_inventory_unchanged": non_caption == source["non_caption"],
        "timeline_geometry_unchanged": geometry == source["geometry"],
        "audio_track_count_unchanged": V1.track_count(target, "audio") == source["audio_track_count"],
        "top_overlay_track_exact": V1.track_count(target, "video") == expected_track and flash.get("rows") and all(int(row.get("track_index") or 0) == expected_track for row in flash["rows"]),
        "one_authorized_flash": flash.get("ok") is True and flash.get("count") == 1 and flash.get("neutral_carrier_count") == 1 and flash.get("source_video_carrier_count") == 0,
    }
    return {"ok": all(checks.values()), "checks": checks, "captions": captions, "non_caption": non_caption, "geometry": geometry, "flash": flash, "expected_flash_track": expected_track}


def exact_flash_item(timeline: Any, spec: Mapping[str, Any], expected_track: int) -> Any:
    matches = [
        item
        for track, item in V1.all_video_items(timeline)
        if track == expected_track
        and V1.item_name(item) == spec["name"]
        and V1.item_start(item) == int(spec["start_frame"])
        and V1.item_duration(item) == int(spec["duration_frames"])
    ]
    if len(matches) != 1:
        raise RuntimeError(f"flash_carrier_identity:{len(matches)}")
    return matches[0]


def persisted_target_contract(source: Mapping[str, Any], target: Any, flashes: list[Mapping[str, Any]]) -> dict[str, Any]:
    contract = target_contract(source, target, flashes)
    item = exact_flash_item(target, flashes[0], int(contract["expected_flash_track"]))
    count = int(V1.safe_call(item, "GetFusionCompCount", default=0) or 0)
    comp = V1.safe_call(item, "GetFusionCompByIndex", 1, default=None) if count >= 1 else None
    persisted = bool(count >= 1 and comp is not None and contract["flash"].get("ok") is True)
    contract["persisted_fusion"] = {"ok": persisted, "fusion_comp_count": count, "reacquired_carrier": True}
    contract["checks"]["flash_fusion_persisted"] = persisted
    contract["ok"] = all(contract["checks"].values())
    return contract


def repairable_partial_target(source: Mapping[str, Any], target: Any, flashes: list[Mapping[str, Any]]) -> dict[str, Any]:
    contract = target_contract(source, target, flashes)
    expected_track = int(contract["expected_flash_track"])
    item = exact_flash_item(target, flashes[0], expected_track)
    row = next((candidate for candidate in contract["flash"].get("rows", []) if candidate.get("name") == flashes[0]["name"]), {})
    structural = all(value for name, value in contract["checks"].items() if name != "one_authorized_flash")
    carrier_ok = bool(
        contract["flash"].get("count") == 1
        and row.get("track_index") == expected_track
        and row.get("start") == int(flashes[0]["start_frame"])
        and row.get("duration") == int(flashes[0]["duration_frames"])
        and row.get("carrier", {}).get("neutral_carrier_ok") is True
        and contract["flash"].get("source_video_carrier_count") == 0
    )
    fusion_count = int(V1.safe_call(item, "GetFusionCompCount", default=0) or 0)
    return {"ok": bool((not contract["ok"] or fusion_count < 1) and structural and carrier_ok), "item": item, "contract": contract, "fusion_comp_count": fusion_count}


def inventory_without_target(project: Any) -> list[dict[str, Any]]:
    return [row for row in P4B.timeline_inventory(project) if row.get("name") != TARGET_TIMELINE_NAME]


def same_inventory(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    key = lambda row: (row.get("name"), row.get("signature"))
    return Counter(map(key, left)) == Counter(map(key, right))


def resolve_gold_source(media_pool: Any, project: Any, root: Path) -> tuple[Any, dict[str, Any]]:
    existing = find_exact(project, GOLD_TIMELINE_NAME, allow_missing=True)
    if existing is not None:
        return existing, {"route": "EXACT_EXISTING_GOLD_TIMELINE", "imported": False}
    drt = root / GOLD_DRT_RELATIVE
    value, call = V1.direct_call(media_pool, "ImportTimelineFromFile", str(drt), {"timelineName": GOLD_TIMELINE_NAME})
    source = find_exact(project, GOLD_TIMELINE_NAME)
    if value is None or V1.timeline_name(source) != GOLD_TIMELINE_NAME:
        raise RuntimeError("gold_drt_import")
    return source, {"route": "IMMUTABLE_GOLD_DRT_IMPORT", "imported": True, "call": call}


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    command = context.get("command") or {}
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    report: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "version": VERSION, "run_id": run_id, "mode": MODE, "failures": [], "save_project_count": 0, "timeline_duplicate_count": 0, "track_add_count": 0, "flash_carrier_append_count": 0, "media_import_count": 0}
    root = report_dir = None
    manager = project = media_pool = source = target = previous = None
    target_created = gold_imported = saved = False
    media_ownership = None
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
        if sha256(plan_path) != payload.get("plan_sha256"):
            raise ValueError("plan_file_hash")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        validate_plan(plan)
        project_name = str(plan["project_name"])
        if payload.get("expected_project") != project_name:
            raise ValueError("payload_identity")
        hashes = verify_input_hashes(root)
        report["authority_verification"] = hashes
        if not hashes["ok"]:
            raise RuntimeError("accepted_authority_hash")
        manager = V1.safe_call(resolve, "GetProjectManager", default=None)
        project = V1.safe_call(manager, "GetCurrentProject", default=None)
        if project is None or str(V1.safe_call(project, "GetName", default="") or "") != project_name:
            raise RuntimeError("project_identity")
        media_pool = V1.safe_call(project, "GetMediaPool", default=None)
        if manager is None or media_pool is None:
            raise RuntimeError("resolve_context")
        report["project_name"] = project_name
        previous = V1.safe_call(project, "GetCurrentTimeline", default=None)
        source, route = resolve_gold_source(media_pool, project, root)
        gold_imported = route.get("imported") is True
        report["gold_source_route"] = route
        source_before = source_state(source)
        flashes = mapped_flash(source_before["geometry"])
        inventory_before = inventory_without_target(project)
        existing = find_exact(project, TARGET_TIMELINE_NAME, allow_missing=True)
        report.update({"run_mode": run_mode, "source_before": source_before, "mapped_flash": flashes, "timeline_inventory_before": inventory_before})
        application_classification = None
        assets = None
        if existing is not None:
            selection = select_and_prove(project, existing)
            report["target_selection"] = selection
            if not selection["ok"]:
                raise RuntimeError("target_selection_readback")
            contract = persisted_target_contract(source_before, existing, flashes)
            if contract["ok"]:
                source_after = source_state(source)
                inventory_after = inventory_without_target(project)
                if not source_unchanged(source_before, source_after) or not same_inventory(inventory_before, inventory_after):
                    raise RuntimeError("idempotency_regression")
                report.update({"ok": True, "classification": "ALREADY_VALID_REUSED", "idempotent": True, "target_after": contract, "source_after": source_after, "source_timeline_unchanged": True, "unrelated_timelines_unchanged": True, "timeline_inventory_after": inventory_after, "persistent_readback_ok": True})
            else:
                if run_mode == "idempotency":
                    raise RuntimeError("flash_fusion_not_persisted")
                repair = repairable_partial_target(source_before, existing, flashes)
                report["partial_target_before"] = {"ok": repair["ok"], "fusion_comp_count": repair["fusion_comp_count"], "contract": V1.json_safe(repair["contract"])}
                if not repair["ok"]:
                    raise RuntimeError("preexisting_target_invalid")
                target = existing
                configured = V1.configure_flash(repair["item"], flashes[0], 1)
                if not configured.get("ok"):
                    raise RuntimeError("flash_configure")
                application_classification = "PARTIAL_TARGET_REPAIRED"
        else:
            if run_mode == "idempotency":
                raise RuntimeError("idempotency_target_missing")
            value, duplicate_call = V1.direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
            target = value if value is not None else find_exact(project, TARGET_TIMELINE_NAME)
            if target is None or V1.timeline_name(target) != TARGET_TIMELINE_NAME:
                raise RuntimeError("duplicate_target")
            target_created = True
            report["timeline_duplicate_count"] = 1
            report["duplicate_call"] = duplicate_call
            selection = select_and_prove(project, target)
            report["target_selection"] = selection
            if not selection["ok"]:
                raise RuntimeError("target_selection_readback")
            duplicate_state = source_state(target)
            if not source_unchanged(source_before, duplicate_state | {"timeline_name": source_before["timeline_name"], "timeline_uid": source_before["timeline_uid"]}):
                raise RuntimeError("duplicate_structural_snapshot")
            source_tracks = int(source_before["video_track_count"])
            track = V1.ensure_extra_video_track(target, source_tracks)
            if not track.get("ok") or int(track.get("target_track") or 0) != source_tracks + 1:
                raise RuntimeError("top_overlay_track")
            report["track_add_count"] = 1
            assets = V4.validate_neutral_assets(root)
            if not assets.get("ok"):
                raise RuntimeError("neutral_assets")
            imported = V4.import_neutral_carrier(media_pool, root, assets)
            media_ownership = imported
            media_item = imported.get("item")
            report["media_ownership"] = {key: V1.json_safe(value) for key, value in imported.items() if key != "item"}
            if not imported.get("ok") or media_item is None:
                raise RuntimeError("neutral_media_ownership")
            report["media_import_count"] = int(imported.get("import_performed") is True)
            appended = V1.append_flash_carriers(media_pool, target, {"media_pool_item": media_item, "source_start": 0}, flashes, source_tracks + 1)
            assigned = list(appended.get("assigned") or [])
            if not appended.get("ok") or len(assigned) != 1:
                raise RuntimeError("flash_append")
            report["flash_carrier_append_count"] = 1
            flash_item = exact_flash_item(target, flashes[0], source_tracks + 1)
            configured = V1.configure_flash(flash_item, flashes[0], 1)
            if not configured.get("ok"):
                raise RuntimeError("flash_configure")
            application_classification = "FIRST_APPLICATION"
        if application_classification is not None:
            before_save = target_contract(source_before, target, flashes)
            source_mid = source_state(source)
            inventory_pre_save = inventory_without_target(project)
            report["timeline_inventory_pre_save"] = inventory_pre_save
            if not before_save["ok"] or not source_unchanged(source_before, source_mid):
                raise RuntimeError("pre_save_non_regression")
            if not same_inventory(inventory_before, inventory_pre_save):
                raise RuntimeError("pre_save_non_target_regression")
            visual = C1.capture_visual_evidence(project, target, flashes, report_dir / "visual_evidence")
            if not visual.get("ok") or visual.get("total_frames") != 4:
                raise RuntimeError("visual_evidence")
            if not V1.safe_call(manager, "SaveProject", default=False):
                raise RuntimeError("save_project")
            saved = True
            report["save_project_count"] = 1
            persistent = find_exact(project, TARGET_TIMELINE_NAME)
            after = persisted_target_contract(source_before, persistent, flashes)
            source_after = source_state(source)
            inventory_after = inventory_without_target(project)
            if not after.get("persisted_fusion", {}).get("ok"):
                raise RuntimeError("flash_fusion_not_persisted")
            if not after["ok"] or not source_unchanged(source_before, source_after) or not same_inventory(inventory_before, inventory_after):
                raise RuntimeError("persistent_readback")
            result = {"ok": True, "classification": application_classification, "idempotent": False, "configure": V1.json_safe(configured), "visual_evidence": visual, "target_after": after, "source_after": source_after, "source_timeline_unchanged": True, "unrelated_timelines_unchanged": True, "timeline_inventory_after": inventory_after, "persistent_readback_ok": True}
            if assets is not None:
                result["neutral_asset_verification"] = assets
            report.update(result)
    except BaseException as exc:
        report["failures"] = [f"{type(exc).__name__}: {exc}"]
        report["traceback"] = traceback.format_exc()
        if not saved and media_pool is not None and (target_created or gold_imported):
            owned_timelines = [timeline for timeline in (target if target_created else None, source if gold_imported else None) if timeline is not None]
            delete_target, delete_call = V1.direct_call(media_pool, "DeleteTimelines", owned_timelines)
            delete_media = V4._delete_owned_media_pool_item(media_pool, media_ownership)
            rollback_save = bool(V1.safe_call(manager, "SaveProject", default=False)) if delete_target else False
            report["rollback"] = {"timeline_delete_ok": bool(delete_target), "owned_timeline_names": [V1.timeline_name(timeline) for timeline in owned_timelines], "timeline_delete_call": delete_call, "media_delete": delete_media, "save_ok": rollback_save, "owned_only": True}
        report["classification"] = "STEP6A_GOLD_FRAME_MAPPING_MISMATCH" if isinstance(exc, FrameMappingError) else "STEP6A_FAILED"
    finally:
        if project is not None and previous is not None:
            report["previous_timeline_restoration"] = select_and_prove(project, previous)
            if not report["previous_timeline_restoration"]["ok"]:
                report["ok"] = False
                report["failures"].append("RuntimeError: previous_timeline_restoration")
        if report_dir is not None:
            try:
                P4B.write_json(report_dir / "step6a_flash_result.json", report)
            except Exception:
                pass
    return report
