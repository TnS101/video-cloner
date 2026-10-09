"""Replace only Reel #3 sub_008 with a native animated Text+ title."""
from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path
from typing import Any


_root = Path(__file__).resolve().parents[1]
_adapter_spec = importlib.util.spec_from_file_location(
    "p006_caption_animation_adapter", _root / "resolve_apply_caption_animation_step_3C.py"
)
if _adapter_spec is None or _adapter_spec.loader is None:
    raise ImportError("caption_animation_adapter")
adapter = importlib.util.module_from_spec(_adapter_spec)
_adapter_spec.loader.exec_module(adapter)

TASK_ID = "VIDEO_CLONER_P006_REEL3_NATIVE_TEXTPLUS_SUB008_CANARY_V1"
MODE = "p006_reel3_native_textplus_sub008_canary"
ACTION = "replace_sub008_with_native_textplus"
CUE_ID = "sub_008"


def _call(obj: Any, method: str, *args: Any, default: Any = None) -> Any:
    function = getattr(obj, method, None)
    return function(*args) if callable(function) else default


def _timeline_identity(timeline: Any) -> dict[str, str]:
    return {
        "name": str(_call(timeline, "GetName", default="") or ""),
        "unique_id": str(_call(timeline, "GetUniqueId", default="") or ""),
    }


def _find_target(project: Any, name: str, uid: str) -> Any:
    matches = []
    for index in range(1, int(_call(project, "GetTimelineCount", default=0) or 0) + 1):
        timeline = _call(project, "GetTimelineByIndex", index)
        if timeline is not None and _timeline_identity(timeline) == {"name": name, "unique_id": uid}:
            matches.append(timeline)
    if len(matches) != 1:
        raise ValueError(f"target_timeline_identity:{len(matches)}")
    return matches[0]


def _textplus_tool(comp: Any) -> Any:
    tools = _call(comp, "GetToolList", False, "TextPlus", default={}) or {}
    values = list(tools.values()) if isinstance(tools, dict) else list(tools or [])
    matches = []
    for tool in values:
        attrs = _call(tool, "GetAttrs", default={}) or {}
        if isinstance(attrs, dict) and str(attrs.get("TOOLS_RegID") or "") == "TextPlus":
            matches.append(tool)
    if len(matches) != 1:
        raise RuntimeError(f"native_textplus_tool_count:{len(matches)}")
    return matches[0]


def _caption_snapshot(items: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": adapter.safe_name(item),
            "start": adapter.safe_start(item),
            "end": adapter.safe_end(item),
            "enabled": _call(item, "GetClipEnabled"),
        }
        for item in items
    ]


def _caption_contract(path: str) -> list[dict[str, Any]]:
    data = adapter.load_json(adapter._repository_path(path))
    rows = list((data.get("structure") or {}).get("caption_contract") or [])
    if len(rows) != 112 or {str(row.get("subtitle_id") or "") for row in rows} != {
        f"sub_{index:03d}" for index in range(1, 113)
    }:
        raise ValueError("caption_contract_112")
    return rows


def _structural_caption_map(timeline: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    base_frame = int(_call(timeline, "GetStartFrame", default=0) or 0)
    mapped: dict[str, Any] = {}
    for row in rows:
        cue_id = str(row["subtitle_id"])
        track = int(row["lane"]) + 1
        relative_start = int(row["timeline_start_frame"])
        duration = int(row["timeline_end_frame"]) - relative_start
        matches = [
            item
            for item in list(_call(timeline, "GetItemListInTrack", "video", track, default=[]) or [])
            if adapter.safe_start(item) is not None
            and adapter.safe_start(item) - base_frame == relative_start
            and adapter.safe_end(item) is not None
            and adapter.safe_end(item) - adapter.safe_start(item) == duration
        ]
        if len(matches) != 1:
            raise ValueError(f"caption_structural_match:{cue_id}:{len(matches)}")
        mapped[cue_id] = matches[0]
    if len(mapped) != 112:
        raise ValueError(f"caption_structural_coverage:{len(mapped)}")
    return mapped


def _semantic_snapshot(mapped: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        cue_id: {
            "start": adapter.safe_start(item),
            "end": adapter.safe_end(item),
            "duration": _call(item, "GetDuration"),
            "enabled": _call(item, "GetClipEnabled"),
        }
        for cue_id, item in mapped.items()
    }


def _native_textplus_candidates(timeline: Any, relative_start: int, duration: int) -> list[dict[str, Any]]:
    base_frame = int(_call(timeline, "GetStartFrame", default=0) or 0)
    candidates = []
    for track in range(1, int(_call(timeline, "GetTrackCount", "video", default=0) or 0) + 1):
        for item in list(_call(timeline, "GetItemListInTrack", "video", track, default=[]) or []):
            start, end = adapter.safe_start(item), adapter.safe_end(item)
            if start is None or end is None or start - base_frame != relative_start or end - start != duration:
                continue
            if int(_call(item, "GetFusionCompCount", default=0) or 0) > 0:
                candidates.append({"track": track, "name": adapter.safe_name(item), "start": start, "end": end})
    return candidates


def _video_inventory(timeline: Any) -> Counter[tuple[Any, ...]]:
    rows: Counter[tuple[Any, ...]] = Counter()
    for track in range(1, int(_call(timeline, "GetTrackCount", "video", default=0) or 0) + 1):
        for item in list(_call(timeline, "GetItemListInTrack", "video", track, default=[]) or []):
            rows[(
                track,
                adapter.safe_name(item),
                adapter.safe_start(item),
                adapter.safe_end(item),
                int(_call(item, "GetFusionCompCount", default=0) or 0),
            )] += 1
    return rows


def _item_signature(item: Any) -> tuple[Any, ...]:
    return (
        adapter.safe_name(item),
        adapter.safe_start(item),
        adapter.safe_end(item),
        int(_call(item, "GetFusionCompCount", default=0) or 0),
    )


def _inventory_tracks_for_item(timeline: Any, item: Any) -> list[int]:
    signature = _item_signature(item)
    return sorted({
        int(key[0])
        for key, count in _video_inventory(timeline).items()
        if count > 0 and key[1:] == signature
    })


def _rollback_inserted_item(timeline: Any, item: Any) -> dict[str, Any]:
    signature = _item_signature(item)
    returned = _call(timeline, "DeleteClips", [item], False, default=False)
    remaining_tracks = _inventory_tracks_for_item(timeline, item)
    return {
        "delete_returned": returned,
        "signature": signature,
        "remaining_tracks": remaining_tracks,
        "gone": not remaining_tracks,
        "ok": returned is True and not remaining_tracks,
    }


def _timecode(frame: int, fps: int) -> str:
    seconds, frames = divmod(frame, fps)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"


def _authority(context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    run_id = str(context.get("run_id") or "")
    command = context.get("command") or {}
    payload = command.get("payload") or {}
    required = {
        "action": ACTION,
        "caption_cue_ids": [CUE_ID],
        "expected_caption_count": 112,
        "expected_untouched_caption_count": 111,
        "target_timeline_only": True,
        "native_textplus_only": True,
        "hide_original_after_verification": True,
        "save_project": False,
        "expected_structural_caption_count": 112,
    }
    if command.get("task") != TASK_ID or command.get("run_id") != run_id or command.get("mode") != MODE:
        raise ValueError("command_identity")
    if any(payload.get(key) != value for key, value in required.items()):
        raise ValueError("sub008_canary_authority")
    return run_id, payload


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id, payload = _authority(context)
    plan = adapter.load_json(adapter._repository_path(payload["animation_plan_path"]))
    rows = [row for row in adapter._selected_plan_items(plan) if row.get("cue_id") == CUE_ID]
    if len(rows) != 1:
        raise ValueError("sub008_plan_identity")
    row = rows[0]
    if (row.get("text"), row.get("start_frame"), row.get("end_frame"), row.get("duration_frames")) != ("this", 39, 44, 5):
        raise ValueError("sub008_plan_contract")
    style = adapter._carrier_static_styles(
        adapter._repository_path(payload["static_fcpxml_path"]), rows, int(payload["frame_width"])
    )[CUE_ID]
    contract_rows = _caption_contract(str(payload["caption_contract_path"]))

    manager = _call(resolve, "GetProjectManager")
    project = _call(manager, "GetCurrentProject")
    if project is None or str(_call(project, "GetName", default="") or "") != str(payload["expected_project"]):
        raise ValueError("project_identity")
    timeline = _find_target(project, str(payload["target_timeline_name"]), str(payload["target_timeline_uid"]))
    if _call(project, "SetCurrentTimeline", timeline, default=False) is not True:
        raise RuntimeError("target_timeline_activation")
    _call(resolve, "OpenPage", "edit")

    mapped_before = _structural_caption_map(timeline, contract_rows)
    semantic_before = _semantic_snapshot(mapped_before)
    original = mapped_before[CUE_ID]
    if semantic_before[CUE_ID]["enabled"] is not True:
        raise ValueError("sub008_original_not_enabled")
    if _native_textplus_candidates(timeline, 39, 5):
        raise ValueError("preexisting_sub008_native_textplus")
    inventory_before = _video_inventory(timeline)

    fps = int(payload["frame_rate"])
    if fps != 24:
        raise ValueError("frame_rate_contract")
    timeline_start = int(_call(timeline, "GetStartFrame", default=0) or 0)
    if _call(timeline, "SetCurrentTimecode", _timecode(timeline_start + 39, fps), default=False) is not True:
        raise RuntimeError("sub008_playhead")
    if _call(timeline, "SetMarkInOut", 39, 43, "video", default=False) is not True:
        raise RuntimeError("sub008_mark_in_out")

    item = None
    original_hidden = False
    try:
        item = _call(timeline, "InsertFusionTitleIntoTimeline", "Text+")
        if item is None or item is False:
            raise RuntimeError("native_textplus_no_returned_item")
        item_start, item_end = adapter.safe_start(item), adapter.safe_end(item)
        if item_start is None or item_end is None or (item_start - timeline_start, item_end - item_start) != (39, 5):
            raise RuntimeError("native_textplus_timing")
        comp_count = int(_call(item, "GetFusionCompCount", default=0) or 0)
        if comp_count != 1:
            raise RuntimeError(f"native_textplus_comp_count:{comp_count}")
        comp = adapter.get_fusion_comp(item)
        if comp is None:
            raise RuntimeError("native_textplus_comp_unavailable")
        tool = _textplus_tool(comp)
        static_result = adapter._apply_static_style(tool, style)
        animation = adapter._runtime_animation(row, tool)
        animation_result = adapter.apply_authorized_animation(comp, tool, animation, 5)
        input_name, targets = adapter.validated_animation_targets(tool, animation, 5)
        if input_name != "Center" or not adapter.input_targets_are_correct(tool, input_name, targets):
            raise RuntimeError("sub008_animation_readback")

        inventory_after_insert = _video_inventory(timeline)
        added = inventory_after_insert - inventory_before
        removed = inventory_before - inventory_after_insert
        diagnostic_tracks = _inventory_tracks_for_item(timeline, item)
        mapped_before_hide = _structural_caption_map(timeline, contract_rows)
        if _semantic_snapshot(mapped_before_hide) != semantic_before:
            raise RuntimeError("caption_changed_before_replacement_verification")

        if _call(original, "SetClipEnabled", False, default=False) is not True:
            raise RuntimeError("sub008_original_hide")
        original_hidden = True
        mapped_after = _structural_caption_map(timeline, contract_rows)
        semantic_after = _semantic_snapshot(mapped_after)
        expected_after = {cue_id: dict(snapshot) for cue_id, snapshot in semantic_before.items()}
        expected_after[CUE_ID]["enabled"] = False
        if semantic_after != expected_after:
            raise RuntimeError("caption_isolation_readback")
        if _timeline_identity(timeline) != {"name": str(payload["target_timeline_name"]), "unique_id": str(payload["target_timeline_uid"])}:
            raise RuntimeError("target_timeline_identity_changed")

        return {
            "ok": True,
            "task_id": TASK_ID,
            "run_id": run_id,
            "target_timeline": _timeline_identity(timeline),
            "cue_id": CUE_ID,
            "insertion_route": "Timeline.InsertFusionTitleIntoTimeline(\"Text+\")",
            "timeline_item": {"name": adapter.safe_name(item), "relative_start": 39, "relative_end": 44, "duration": 5, "fusion_comp_count": 1},
            "diagnostic_track_indexes": diagnostic_tracks,
            "diagnostic_inventory_delta": {
                "added_count": sum(added.values()),
                "removed_count": sum(removed.values()),
            },
            "textplus": {"styled_text": style["text"], "tool_regid": "TextPlus", "static_style": static_result},
            "animation": animation_result,
            "original_sub008_hidden": True,
            "untouched_caption_count": 111,
            "structural_caption_coverage": 112,
            "duplicate_visible_sub008": False,
            "save_project_count": 0,
        }
    except Exception as exc:
        restore_ok = True
        if original_hidden:
            restored = _call(original, "SetClipEnabled", True, default=False)
            restore_ok = restored is True and _call(original, "GetClipEnabled") is True
        if item is not None:
            cleanup = _rollback_inserted_item(timeline, item)
            try:
                rollback_state_ok = _semantic_snapshot(_structural_caption_map(timeline, contract_rows)) == semantic_before
            except Exception:
                rollback_state_ok = False
            if not cleanup["ok"] or not restore_ok or not rollback_state_ok:
                raise RuntimeError(
                    f"sub008_rollback_failed:cleanup={cleanup}:original_restored={restore_ok}:"
                    f"semantic_state_restored={rollback_state_ok}"
                ) from exc
            raise RuntimeError(f"sub008_canary_failed_rollback_verified:{type(exc).__name__}:{exc}") from exc
        if not restore_ok:
            raise RuntimeError("sub008_original_restore_failed") from exc
        raise
    finally:
        _call(timeline, "ClearMarkInOut", "video")
