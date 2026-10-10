"""Disposable compatibility check for the proven nested-timeline Text+ route.

Adapted from samuelgursky/davinci-resolve-mcp, commit
94c7a885d53f13be78522ce96561a9e9e21d64c5,
tests/live_workaround_verification.py::case_nested_title (MIT License).
"""
from __future__ import annotations

from typing import Any


TASK_ID = "OSS001_NESTED_TEXTPLUS_COMPAT_V1"
MODE = "disposable_nested_textplus_compat"
SOURCE_TIMELINE = "_VC_OSS001_TEXTPLUS_SOURCE"
TARGET_TIMELINE = "_VC_OSS001_TEXTPLUS_TARGET"
INITIAL_TEXT = "VC_OSS001_NESTED_TEXTPLUS_PROVEN_ROUTE"
EDITED_TEXT = INITIAL_TEXT + "_EDITED_AFTER_PLACEMENT"
REQUESTED_TRACK = 3
REQUESTED_OFFSET = 100
REQUESTED_DURATION = 90


def _call(obj: Any, method: str, *args: Any) -> Any:
    if obj is None:
        raise ValueError(f"{method}_owner_missing")
    try:
        return getattr(obj, method)(*args)
    except Exception as exc:
        raise ValueError(f"{method}_failed:{exc}") from exc


def _timelines(project: Any) -> list[Any]:
    count = int(_call(project, "GetTimelineCount") or 0)
    return [_call(project, "GetTimelineByIndex", index) for index in range(1, count + 1)]


def _name(value: Any) -> str:
    return str(_call(value, "GetName") or "")


def _timeline_key(timeline: Any) -> tuple[str, str]:
    try:
        unique_id = str(timeline.GetUniqueId() or "")
    except Exception:
        unique_id = ""
    return _name(timeline), unique_id


def _find_textplus(timeline: Any) -> tuple[Any, Any]:
    found: list[tuple[Any, Any]] = []
    for track in range(1, int(_call(timeline, "GetTrackCount", "video") or 0) + 1):
        for item in _call(timeline, "GetItemListInTrack", "video", track) or []:
            if int(_call(item, "GetFusionCompCount") or 0) != 1:
                continue
            comp = _call(item, "GetFusionCompByIndex", 1)
            tool = _call(comp, "FindTool", "Template")
            if tool is not None:
                found.append((item, tool))
    if len(found) != 1:
        raise ValueError(f"textplus_count:{len(found)}")
    return found[0]


def _set_and_read_text(tool: Any, value: str, label: str) -> str:
    _call(tool, "SetInput", "StyledText", value)
    actual = _call(tool, "GetInput", "StyledText")
    if actual != value:
        raise ValueError(f"{label}_mismatch:{actual!r}")
    return str(actual)


def verify_route(project: Any, pool: Any, source: Any, target: Any) -> dict[str, Any]:
    """Port the upstream route and reject every unverified API return."""
    if not bool(_call(project, "SetCurrentTimeline", source)):
        raise ValueError("source_timeline_select")
    _call(source, "InsertFusionTitleIntoTimeline", "Text+")
    _, source_tool = _find_textplus(source)
    initial_readback = _set_and_read_text(source_tool, INITIAL_TEXT, "initial_styled_text")

    source_item = _call(source, "GetMediaPoolItem")
    if source_item is None:
        raise ValueError("source_timeline_media_pool_item_missing")
    if int(_call(target, "GetTrackCount", "video") or 0) < REQUESTED_TRACK:
        raise ValueError("target_video_track_count")
    if not bool(_call(project, "SetCurrentTimeline", target)):
        raise ValueError("target_timeline_select")
    target_start = int(_call(target, "GetStartFrame"))
    requested_start = target_start + REQUESTED_OFFSET
    placed = _call(pool, "AppendToTimeline", [{
        "mediaPoolItem": source_item,
        "startFrame": 0,
        "endFrame": REQUESTED_DURATION,
        "trackIndex": REQUESTED_TRACK,
        "recordFrame": requested_start,
    }])
    if not isinstance(placed, (list, tuple)) or len(placed) != 1 or placed[0] is None:
        raise ValueError(f"append_result_count:{len(placed) if isinstance(placed, (list, tuple)) else 0}")
    item = placed[0]
    track_type, track_index = _call(item, "GetTrackTypeAndIndex")
    actual = {
        "track_type": track_type,
        "track": int(track_index),
        "start": int(_call(item, "GetStart")),
        "duration": int(_call(item, "GetDuration")),
    }
    expected = {"track_type": "video", "track": REQUESTED_TRACK, "start": requested_start, "duration": REQUESTED_DURATION}
    if actual != expected:
        raise ValueError(f"placement_mismatch:expected={expected!r}:actual={actual!r}")

    placed_pool_item = _call(item, "GetMediaPoolItem")
    if placed_pool_item is None:
        raise ValueError("placed_media_pool_item_missing")
    inner = _call(placed_pool_item, "GetTimeline")
    if inner is None:
        raise ValueError("inner_timeline_missing")
    if _timeline_key(inner) != _timeline_key(source):
        raise ValueError("inner_timeline_identity")
    _, inner_tool = _find_textplus(inner)
    edited_readback = _set_and_read_text(inner_tool, EDITED_TEXT, "post_placement_styled_text")
    return {
        "requested": expected,
        "actual": actual,
        "end_frame_exclusive": True,
        "source_timeline": _name(source),
        "target_timeline": _name(target),
        "inner_timeline": _name(inner),
        "initial_styled_text": initial_readback,
        "edited_styled_text": edited_readback,
        "editable_after_placement": True,
    }


def _delete_owned(pool: Any, timelines: list[Any]) -> dict[str, Any]:
    requested = [_timeline_key(row) for row in timelines if row is not None]
    calls = []
    for timeline in reversed(timelines):
        if timeline is not None:
            calls.append(bool(_call(pool, "DeleteTimelines", [timeline])))
    return {"requested": requested, "delete_calls": calls}


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "mode": MODE, "run_id": run_id, "failures": []}
    project = pool = original = source = target = None
    try:
        result["resolve_version"] = str(_call(resolve, "GetVersionString") or "")
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        if command.get("task") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id:
            raise ValueError("command_identity")
        expected_payload = {
            "expected_project": "New Project 1",
            "source_timeline": SOURCE_TIMELINE,
            "target_timeline": TARGET_TIMELINE,
            "requested_track": REQUESTED_TRACK,
            "requested_offset": REQUESTED_OFFSET,
            "requested_duration": REQUESTED_DURATION,
            "cleanup_required": True,
            "save_project": False,
        }
        if any(payload.get(key) != value for key, value in expected_payload.items()):
            raise ValueError("payload_contract")
        manager = _call(resolve, "GetProjectManager")
        project = _call(manager, "GetCurrentProject")
        if project is None or _name(project) != expected_payload["expected_project"]:
            raise ValueError(f"project_identity:{_name(project) if project else ''}")
        pool = _call(project, "GetMediaPool")
        original = _call(project, "GetCurrentTimeline")
        names_before = [_name(row) for row in _timelines(project)]
        if SOURCE_TIMELINE in names_before or TARGET_TIMELINE in names_before:
            raise ValueError("disposable_timeline_name_collision")

        source = _call(pool, "CreateEmptyTimeline", SOURCE_TIMELINE)
        if source is None or _name(source) != SOURCE_TIMELINE:
            raise ValueError("source_timeline_create")
        if not bool(_call(project, "SetCurrentTimeline", source)):
            raise ValueError("source_timeline_select")
        target = _call(pool, "CreateEmptyTimeline", TARGET_TIMELINE)
        if target is None or _name(target) != TARGET_TIMELINE:
            raise ValueError("target_timeline_create")
        if not bool(_call(project, "SetCurrentTimeline", target)):
            raise ValueError("target_timeline_select")
        for _ in range(int(_call(target, "GetTrackCount", "video") or 0), REQUESTED_TRACK):
            if not bool(_call(target, "AddTrack", "video")):
                raise ValueError("target_add_video_track")
        if int(_call(target, "GetTrackCount", "video") or 0) < REQUESTED_TRACK:
            raise ValueError("target_video_track_count")
        result["readback"] = verify_route(project, pool, source, target)
        result["project_name"] = _name(project)
        result["ok"] = True
    except Exception as exc:
        result["failures"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if project is not None and pool is not None:
            try:
                if original is not None and not bool(_call(project, "SetCurrentTimeline", original)):
                    raise ValueError("original_timeline_restore")
                cleanup = _delete_owned(pool, [source, target])
                remaining = [_timeline_key(row) for row in _timelines(project)]
                cleanup["remaining_owned"] = [row for row in cleanup["requested"] if row in remaining]
                cleanup["original_timeline_restored"] = original is None or _timeline_key(_call(project, "GetCurrentTimeline")) == _timeline_key(original)
                cleanup["ok"] = all(cleanup["delete_calls"]) and not cleanup["remaining_owned"] and cleanup["original_timeline_restored"]
                result["cleanup"] = cleanup
                if not cleanup["ok"]:
                    result["ok"] = False
                    result["failures"].append("ValueError: cleanup_readback")
            except Exception as exc:
                result["ok"] = False
                result["failures"].append(f"cleanup:{type(exc).__name__}: {exc}")
    return result
