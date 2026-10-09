"""Read-only probe for residual native Text+ state at Reel #3 sub_008."""
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

TASK_ID = "VIDEO_CLONER_P006_SUB008_PARTIAL_STATE_READONLY_V1"
MODE = "p006_sub008_partial_state_readonly"
ACTION = "inspect_sub008_partial_state_read_only"


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


def _textplus_tools(comp: Any) -> list[Any]:
    tools = _call(comp, "GetToolList", False, "TextPlus", default={}) or {}
    values = list(tools.values()) if isinstance(tools, dict) else list(tools or [])
    return [
        tool for tool in values
        if str((_call(tool, "GetAttrs", default={}) or {}).get("TOOLS_RegID") or "") == "TextPlus"
    ]


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    command = context.get("command") or {}
    payload = command.get("payload") or {}
    required = {
        "action": ACTION,
        "read_only": True,
        "zero_mutation": True,
        "save_project": False,
        "delete_permitted": False,
        "retry_permitted": False,
    }
    if command.get("task") != TASK_ID or command.get("run_id") != run_id or command.get("mode") != MODE:
        raise ValueError("command_identity")
    if any(payload.get(key) != value for key, value in required.items()):
        raise ValueError("read_only_authority")

    manager = _call(resolve, "GetProjectManager")
    project = _call(manager, "GetCurrentProject")
    if project is None or str(_call(project, "GetName", default="") or "") != str(payload["expected_project"]):
        raise ValueError("project_identity")
    timeline = _call(project, "GetCurrentTimeline")
    expected_identity = {
        "name": str(payload["target_timeline_name"]),
        "unique_id": str(payload["target_timeline_uid"]),
    }
    if timeline is None or _identity(timeline) != expected_identity:
        raise ValueError(f"current_timeline_identity:{_identity(timeline) if timeline else None}")

    plan = adapter.load_json(adapter._repository_path(payload["animation_plan_path"]))
    planned = list(plan.get("items") or [])
    if len(planned) != 112:
        raise ValueError("caption_plan_count")
    caption_track = int(payload["caption_track_index"])
    captions = adapter._caption_items(timeline, caption_track)
    caption_differences = []
    bound: dict[str, Any] = {}
    for row in planned:
        matches = [
            item for item in captions
            if adapter.safe_start(item) == int(row["start_frame"])
            and adapter.safe_end(item) == int(row["end_frame"])
        ]
        cue_id = str(row["cue_id"])
        if len(matches) != 1:
            caption_differences.append({"cue_id": cue_id, "issue": "geometry_match_count", "count": len(matches)})
        else:
            bound[cue_id] = matches[0]
            expected_name = f"VC Caption {int(row['cue_index'])}"
            actual_name = adapter.safe_name(matches[0])
            if actual_name != expected_name:
                caption_differences.append({"cue_id": cue_id, "issue": "name", "expected": expected_name, "actual": actual_name})
    original = bound.get("sub_008")
    original_enabled = _call(original, "GetClipEnabled") if original is not None else None
    other_differences = list(caption_differences)
    for cue_id, item in bound.items():
        if cue_id != "sub_008" and _call(item, "GetClipEnabled") is not True:
            other_differences.append({"cue_id": cue_id, "issue": "enabled", "actual": _call(item, "GetClipEnabled")})
    if len(captions) != 112:
        other_differences.append({"issue": "caption_count", "expected": 112, "actual": len(captions)})

    candidates = []
    track_count = int(_call(timeline, "GetTrackCount", "video", default=0) or 0)
    for track in range(1, track_count + 1):
        for item in list(_call(timeline, "GetItemListInTrack", "video", track, default=[]) or []):
            if track == caption_track and item is original:
                continue
            start, end = adapter.safe_start(item), adapter.safe_end(item)
            comp_count = int(_call(item, "GetFusionCompCount", default=0) or 0)
            if start != 39 or end != 44 or comp_count < 1:
                continue
            comp = adapter.get_fusion_comp(item)
            tools = _textplus_tools(comp) if comp is not None else []
            candidates.append({
                "track_index": track,
                "item_name": adapter.safe_name(item),
                "start_frame": start,
                "end_frame": end,
                "fusion_comp_count": comp_count,
                "textplus_tool_count": len(tools),
                "styled_text": adapter.read_input(tools[0], "StyledText", 0) if len(tools) == 1 else None,
            })

    return {
        "ok": True,
        "task_id": TASK_ID,
        "run_id": run_id,
        "target_timeline": expected_identity,
        "partial_native_textplus_exists": bool(candidates),
        "partial_native_textplus_count": len(candidates),
        "native_textplus_candidates": candidates,
        "original_sub008": {
            "found": original is not None,
            "name": adapter.safe_name(original) if original is not None else None,
            "start_frame": adapter.safe_start(original) if original is not None else None,
            "end_frame": adapter.safe_end(original) if original is not None else None,
            "enabled": original_enabled,
        },
        "caption_count": len(captions),
        "other_caption_changed": bool(other_differences),
        "other_caption_differences": other_differences,
        "mutation_counts": {"writes": 0, "deletes": 0, "saves": 0},
    }

