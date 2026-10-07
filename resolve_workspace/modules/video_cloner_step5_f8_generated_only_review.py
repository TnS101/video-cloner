"""Create one persistent generated-only F8 review timeline from accepted F7."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_phase6_textplus_application as carrier
from resolve_workspace.modules import video_cloner_step5_f7_validation_rebuild as f7

TASK_ID = "VIDEO_CLONER_STEP5_F8_GENERATED_ONLY_REVIEW_V1"
MODE = "create_f8_generated_only_review"


def _all_items(timeline: Any, track_type: str) -> list[tuple[int, Any]]:
    return [
        (track, item)
        for track in range(1, int(carrier._safe(timeline, "GetTrackCount", track_type, default=0) or 0) + 1)
        for item in list(carrier._safe(timeline, "GetItemListInTrack", track_type, track, default=[]) or [])
    ]


def _delete_underlay(timeline: Any) -> dict[str, Any]:
    video = [item for _track, item in _all_items(timeline, "video") if int(carrier._safe(item, "GetFusionCompCount", default=0) or 0) == 0]
    audio = [item for _track, item in _all_items(timeline, "audio")]
    subtitle = [item for _track, item in _all_items(timeline, "subtitle")]
    items = [*video, *audio, *subtitle]
    deleted = bool(carrier._safe(timeline, "DeleteClips", items, False, default=False)) if items else True
    return {"ok": deleted, "video_items": len(video), "audio_items": len(audio), "subtitle_items": len(subtitle), "total": len(items)}


def _readback(timeline: Any, contract: dict[str, Any]) -> dict[str, Any]:
    expected = {(int(row["z_order_track"]["resolve_track"]), *row["resolve_interval"]): row for row in contract["objects"]}
    generated, source_items, extras = [], [], []
    for track, item in _all_items(timeline, "video"):
        fusion_count = int(carrier._safe(item, "GetFusionCompCount", default=0) or 0)
        key = (track, int(carrier._safe(item, "GetStart", default=-1)), int(carrier._safe(item, "GetEnd", default=-1)))
        if fusion_count == 0:
            source_items.append({"track": track, "start": key[1], "end": key[2], "name": str(carrier._safe(item, "GetName", default="") or "")})
        elif key in expected:
            generated.append(f7.IMPLEMENTATION._read(item, expected[key], track))
        else:
            extras.append({"track": track, "start": key[1], "end": key[2], "name": str(carrier._safe(item, "GetName", default="") or "")})
    subtitle_count = len(_all_items(timeline, "subtitle"))
    audio_count = len(_all_items(timeline, "audio"))
    parity = f7.IMPLEMENTATION._parity(contract, generated)
    expected_ids = {row["source_identity"] for row in contract["objects"]}
    actual_ids = {row["source_identity"] for row in generated}
    target_6000 = next(row for row in contract["objects"] if row["source_identity"] == "caption_tracklet_0089")
    width = str(carrier._safe(timeline, "GetSetting", "timelineResolutionWidth", default="") or "")
    height = str(carrier._safe(timeline, "GetSetting", "timelineResolutionHeight", default="") or "")
    return {
        "generated_object_count": len(generated),
        "source_or_proxy_video_item_count": len(source_items),
        "subtitle_item_count": subtitle_count,
        "audio_item_count": audio_count,
        "other_text_or_generated_extra_count": len(extras),
        "expected_identity_count": len(expected_ids),
        "missing_identity_count": len(expected_ids - actual_ids),
        "unexpected_generated_identity_count": len(actual_ids - expected_ids),
        "text_mismatch_count": 0 if parity["ok"] else None,
        "lifecycle_mismatch_count": 0 if parity["ok"] else None,
        "style_mismatch_count": 0 if parity["ok"] else None,
        "position_mismatch_count": 0 if parity["ok"] else None,
        "scale_mismatch_count": 0 if parity["ok"] else None,
        "f6_6000_interval": target_6000["resolve_interval"],
        "f3_6000_scale_key_count": len(target_6000["keyframes"]["scale"]),
        "source_items": source_items,
        "extras": extras,
        "timeline_resolution": [width, height],
        "neutral_background_strategy": "NO_MEDIA_UNDERLAY; RESOLVE_TRANSPARENT_VIEWER_PRESENTS_NEUTRAL_BLACK",
        "parity": parity,
        "objects": sorted(generated, key=lambda row: row["source_identity"]),
        "ok": len(generated) == len(expected_ids) and not source_items and not subtitle_count and not audio_count and not extras and parity["ok"] and [width, height] == ["1080", "1920"] and target_6000["resolve_interval"] == [542, 596] and len(target_6000["keyframes"]["scale"]) == 9,
    }


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    command = context.get("command") or {}
    payload = command.get("payload") or {}
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "run_id": run_id, "classification": "BLOCKED", "mutation_counts": {"timeline_create": 0, "underlay_delete": 0, "project_save": 0, "rollback_delete": 0}}
    project = manager = previous = target = None
    created = saved = success = False
    report_dir = Path(str(payload.get("report_dir") or ROOT / ".agent/reports" / TASK_ID / run_id)).resolve()
    try:
        if command.get("task_id") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id:
            raise ValueError("command_identity")
        contract_path = Path(str(payload["contract_path"])).resolve()
        if f7.IMPLEMENTATION.base.sha(contract_path) != payload.get("contract_sha256"):
            raise ValueError("contract_hash")
        contract = f7.IMPLEMENTATION.base.read(contract_path)
        if int(contract.get("object_count") or 0) <= 0 or len(contract.get("objects", [])) != contract["object_count"]:
            raise ValueError("contract_scope")
        manager = carrier._safe(resolve, "GetProjectManager")
        project = carrier._safe(manager, "GetCurrentProject")
        if project is None or carrier._safe(project, "GetName", default="") != contract["project"]:
            raise ValueError("project_identity")
        protected = f7.IMPLEMENTATION.base.find_timeline(project, contract["protected_timeline"]["name"], contract["protected_timeline"]["unique_id"])
        source = f7.IMPLEMENTATION.base.find_timeline(project, payload["f7_timeline"], payload["f7_timeline_uid"])
        if protected is None or source is None:
            raise ValueError("source_timeline_identity")
        if f7.IMPLEMENTATION.base.find_timeline(project, payload["review_timeline"]) is not None:
            raise ValueError("fresh_target_already_exists")
        previous = carrier._safe(project, "GetCurrentTimeline", default=None)
        protected_before = f7.IMPLEMENTATION.base.protected_snapshot(protected)
        f7_before = carrier.timeline_snapshot(source)
        before_ids = {carrier._unique_id(row) for row in carrier._timelines(project)}
        returned = carrier._safe(source, "DuplicateTimeline", payload["review_timeline"], default=None)
        delta = [row for row in carrier._timelines(project) if carrier._unique_id(row) not in before_ids]
        target = returned if returned not in (None, False, True) else delta[0] if len(delta) == 1 else None
        if target is None or len(delta) != 1:
            raise ValueError("target_ownership")
        created = True
        result["mutation_counts"]["timeline_create"] = 1
        if not carrier._safe(project, "SetCurrentTimeline", target, default=False):
            raise ValueError("target_activation")
        deletion = _delete_underlay(target)
        result["underlay_deletion"] = deletion
        result["mutation_counts"]["underlay_delete"] = deletion["total"] if deletion["ok"] else 0
        if not deletion["ok"]:
            raise ValueError("underlay_delete")
        if carrier._safe(manager, "SaveProject", default=False) is False:
            raise ValueError("save_project")
        saved = True
        result["mutation_counts"]["project_save"] = 1
        project = carrier._safe(manager, "GetCurrentProject")
        persisted_target = f7.IMPLEMENTATION.base.find_timeline(project, payload["review_timeline"])
        if persisted_target is None:
            raise ValueError("persisted_target_missing")
        target = persisted_target
        check = _readback(target, contract)
        protected_after = f7.IMPLEMENTATION.base.protected_snapshot(f7.IMPLEMENTATION.base.find_timeline(project, contract["protected_timeline"]["name"], contract["protected_timeline"]["unique_id"]))
        f7_after = carrier.timeline_snapshot(f7.IMPLEMENTATION.base.find_timeline(project, payload["f7_timeline"], payload["f7_timeline_uid"]))
        check.update({"review_timeline_exists": True, "project_save_succeeded": True, "protected_timeline_unchanged": protected_before == protected_after, "f7_timeline_unchanged": f7_before == f7_after})
        check["ok"] = check["ok"] and check["protected_timeline_unchanged"] and check["f7_timeline_unchanged"]
        f7.IMPLEMENTATION.base.write(report_dir / "f8_generated_only_machine_check.json", check)
        if not check["ok"]:
            raise ValueError("machine_check")
        success = True
        result.update({"ok": True, "classification": "READY_FOR_F8_HUMAN_REVIEW", "review_timeline": {"name": payload["review_timeline"], "unique_id": carrier._unique_id(target)}, "machine_check": str(report_dir / "f8_generated_only_machine_check.json")})
    except BaseException as exc:
        result["error"] = f7.IMPLEMENTATION.visual.base.compact_exception(exc)
    finally:
        if project is not None and previous is not None:
            carrier._safe(project, "SetCurrentTimeline", previous, default=False)
        if created and not success and project is not None and target is not None:
            deleted = bool(carrier._safe(carrier._safe(project, "GetMediaPool"), "DeleteTimelines", [target], default=False))
            result["mutation_counts"]["rollback_delete"] = int(deleted)
            result["rollback"] = {"owned_timeline_deleted": deleted, "project_resaved": bool(carrier._safe(manager, "SaveProject", default=False)) if deleted and saved else not saved}
        f7.IMPLEMENTATION.base.write(report_dir / "f8_generated_only_review.json", result)
    return result
