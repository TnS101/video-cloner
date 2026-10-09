"""Bounded native Text+ canary on an empty temporary Resolve timeline."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


_adapter_path = Path(__file__).resolve().parents[1] / "resolve_apply_caption_animation_step_3C.py"
_spec = importlib.util.spec_from_file_location("p006_caption_animation_adapter", _adapter_path)
if _spec is None or _spec.loader is None:
    raise ImportError("caption_animation_adapter")
adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adapter)

TASK_ID = "VIDEO_CLONER_P006_NATIVE_TEXTPLUS_CANARY_V1"
MODE = "p006_native_textplus_temporary_timeline_canary"
ACTION = "native_textplus_canary"


def _call(obj: Any, method: str, *args: Any, default: Any = None) -> Any:
    try:
        function = getattr(obj, method, None)
        return function(*args) if callable(function) else default
    except Exception:
        return default


def _identity(timeline: Any) -> dict[str, str]:
    return {
        "name": str(_call(timeline, "GetName", default="") or ""),
        "unique_id": str(_call(timeline, "GetUniqueId", default="") or ""),
    }


def _timeline_snapshot(timeline: Any) -> dict[str, Any]:
    rows = []
    for kind in ("video", "audio"):
        count = int(_call(timeline, "GetTrackCount", kind, default=0) or 0)
        for track in range(1, count + 1):
            for item in list(_call(timeline, "GetItemListInTrack", kind, track, default=[]) or []):
                properties = _call(item, "GetProperty", default={}) or {}
                rows.append({
                    "kind": kind,
                    "track": track,
                    "name": str(_call(item, "GetName", default="") or ""),
                    "start": _call(item, "GetStart"),
                    "end": _call(item, "GetEnd"),
                    "duration": _call(item, "GetDuration"),
                    "opacity": properties.get("Opacity") if isinstance(properties, dict) else None,
                    "fusion_comp_count": _call(item, "GetFusionCompCount", default=0),
                })
    return {**_identity(timeline), "items": rows}


def _timelines(project: Any) -> list[Any]:
    count = int(_call(project, "GetTimelineCount", default=0) or 0)
    return [_call(project, "GetTimelineByIndex", index) for index in range(1, count + 1)]


def _find_timeline(project: Any, name: str, uid: str = "") -> Any:
    matches = [timeline for timeline in _timelines(project) if timeline is not None and _identity(timeline)["name"] == name]
    if uid:
        matches = [timeline for timeline in matches if _identity(timeline)["unique_id"] == uid]
    if len(matches) != 1:
        raise ValueError(f"timeline_identity:{name}:{len(matches)}")
    return matches[0]


def _textplus_tool(comp: Any) -> Any:
    tools = _call(comp, "GetToolList", False, "TextPlus", default=None)
    if not isinstance(tools, (dict, list, tuple)):
        tools = _call(comp, "GetToolList", False, default={})
    values = list(tools.values()) if isinstance(tools, dict) else list(tools or [])
    matches = []
    for tool in values:
        attrs = _call(tool, "GetAttrs", default={}) or {}
        if isinstance(attrs, dict) and str(attrs.get("TOOLS_RegID") or "") == "TextPlus":
            matches.append(tool)
    if len(matches) != 1:
        raise RuntimeError(f"native_textplus_tool_count:{len(matches)}")
    return matches[0]


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    command = context.get("command") or {}
    payload = command.get("payload") or {}
    required = {
        "action": ACTION,
        "temporary_timeline_only": True,
        "target_timeline_mutation_permitted": False,
        "custom_media_carrier_permitted": False,
        "save_project": False,
        "cleanup_temporary_timeline": False,
    }
    if command.get("task") != TASK_ID or command.get("run_id") != run_id or command.get("mode") != MODE:
        raise ValueError("command_identity")
    if any(payload.get(key) != value for key, value in required.items()):
        raise ValueError("native_canary_authority")

    manager = _call(resolve, "GetProjectManager")
    project = _call(manager, "GetCurrentProject")
    if project is None or str(_call(project, "GetName", default="") or "") != str(payload.get("expected_project") or ""):
        raise ValueError("project_identity")
    target = _find_timeline(project, str(payload["target_timeline_name"]), str(payload["target_timeline_uid"]))
    target_before = _timeline_snapshot(target)
    canary_name = str(payload["temporary_timeline_name"])
    if any(_identity(timeline)["name"] == canary_name for timeline in _timelines(project) if timeline is not None):
        raise ValueError("temporary_timeline_exists")

    pool = _call(project, "GetMediaPool")
    canary = _call(pool, "CreateEmptyTimeline", canary_name)
    if canary is None or _identity(canary)["name"] != canary_name:
        raise RuntimeError("temporary_timeline_creation")
    if _call(project, "SetCurrentTimeline", canary, default=False) is not True:
        raise RuntimeError("temporary_timeline_activation")
    _call(resolve, "OpenPage", "edit")
    timecode = str(payload.get("playhead_timecode") or "01:00:00:00")
    if _call(canary, "SetCurrentTimecode", timecode, default=False) is not True:
        raise RuntimeError("native_canary_playhead")

    item = _call(canary, "InsertFusionTitleIntoTimeline", "Text+")
    if item is None or item is False:
        raise RuntimeError("native_textplus_no_returned_timeline_item")
    comp_count = int(_call(item, "GetFusionCompCount", default=0) or 0)
    if comp_count != 1:
        raise RuntimeError(f"native_textplus_comp_count:{comp_count}")
    comp = adapter.get_fusion_comp(item)
    if comp is None:
        raise RuntimeError("native_textplus_comp_unavailable")
    tool = _textplus_tool(comp)
    text = str(payload.get("styled_text") or "")
    returned = _call(tool, "SetInput", "StyledText", text)
    text_readback = adapter.read_input(tool, "StyledText", 0)
    if str(text_readback or "") != text:
        raise RuntimeError(f"native_textplus_text_readback:{returned!r}:{text_readback!r}")

    duration = int(_call(item, "GetDuration", default=0) or 0)
    if duration < 3:
        raise RuntimeError(f"native_textplus_duration:{duration}")
    last = min(duration - 1, 23)
    middle = min(last - 1, max(1, last // 2))
    animation = {
        "authority": "visual_observed",
        "source_evidence_id": "p006_native_textplus_canary",
        "source_type": "slide",
        "property": "Center",
        "keyframes": [
            {"frame": 0, "relative_time": 0.0, "value": [0.47, 0.5]},
            {"frame": middle, "relative_time": middle / last, "value": [0.5, 0.5]},
            {"frame": last, "relative_time": 1.0, "value": [0.5, 0.5]},
        ],
    }
    animation_result = adapter.apply_authorized_animation(comp, tool, animation, duration)
    input_name, targets = adapter.validated_animation_targets(tool, animation, duration)
    if input_name != "Center" or not adapter.input_targets_are_correct(tool, input_name, targets):
        raise RuntimeError("native_textplus_animation_readback")

    target_after = _timeline_snapshot(target)
    if target_after != target_before:
        raise RuntimeError("target_timeline_changed")
    return {
        "ok": True,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "temporary_timeline": _identity(canary),
        "target_timeline": _identity(target),
        "target_untouched": True,
        "insertion_route": "Timeline.InsertFusionTitleIntoTimeline(\"Text+\")",
        "timeline_item": {
            "name": str(_call(item, "GetName", default="") or ""),
            "start": _call(item, "GetStart"),
            "end": _call(item, "GetEnd"),
            "duration": duration,
            "fusion_comp_count": comp_count,
        },
        "textplus": {"styled_text": str(text_readback), "tool_regid": "TextPlus"},
        "animation": animation_result,
        "animation_property": "Center",
        "modifier": "Path",
        "save_project_count": 0,
        "temporary_timeline_retained_for_review": True,
    }
