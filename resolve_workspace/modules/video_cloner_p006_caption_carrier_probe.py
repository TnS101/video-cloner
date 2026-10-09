"""Read-only Resolve inventory for one geometry-bound Reel #3 caption."""
from __future__ import annotations

from typing import Any


TASK_ID = "VIDEO_CLONER_P006_CAPTION_CARRIER_PROBE_V1"
MODE = "p006_readonly_caption_carrier_probe"
ACTION = "inspect_caption_carrier_read_only"

MUTATION_COUNTS = {
    "project_saves": 0,
    "timeline_selections": 0,
    "caption_writes": 0,
    "fusion_comps_added": 0,
    "fusion_tools_added": 0,
    "fusion_modifiers_added": 0,
    "fusion_inputs_written": 0,
    "properties_written": 0,
    "items_deleted": 0,
    "items_replaced": 0,
}


def _safe_call(obj: Any, method: str, *args: Any) -> tuple[Any, dict[str, Any]]:
    row = {"method": method, "available": False, "ok": False, "return_type": None, "value": None, "error": None}
    try:
        function = getattr(obj, method, None)
        row["available"] = callable(function)
        if not callable(function):
            return None, row
        value = function(*args)
        row.update({"ok": True, "return_type": type(value).__name__, "value": _json_safe(value)})
        return value, row
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
        return None, row


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in list(value.items())[:200]}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in list(value)[:200]]
    try:
        return repr(value)
    except Exception:
        return f"<{type(value).__name__}>"


def _entries(value: Any) -> tuple[list[tuple[Any, Any]], dict[str, Any]]:
    structure = {"type": type(value).__name__, "keys": None, "length": None, "error": None}
    if isinstance(value, dict):
        rows = list(value.items())
        structure.update({"keys": [_json_safe(key) for key, _ in rows], "length": len(rows)})
        return rows, structure
    if isinstance(value, (list, tuple)):
        rows = list(enumerate(value))
        structure["length"] = len(rows)
        return rows, structure
    try:
        rows = list(value.items())
        structure.update({"keys": [_json_safe(key) for key, _ in rows], "length": len(rows)})
        return rows, structure
    except Exception as exc:
        structure["error"] = f"{type(exc).__name__}: {exc}"
        return [], structure


def _tool_inventory(tool: Any, collection_key: Any) -> dict[str, Any]:
    attrs, attrs_call = _safe_call(tool, "GetAttrs")
    attrs = attrs if isinstance(attrs, dict) else {}
    raw_inputs, inputs_call = _safe_call(tool, "GetInputList")
    input_entries, input_structure = _entries(raw_inputs) if raw_inputs is not None else ([], {"type": "NoneType", "keys": None, "length": 0, "error": None})
    inputs = []
    for key, input_object in input_entries:
        input_attrs, input_attrs_call = _safe_call(input_object, "GetAttrs")
        input_attrs = input_attrs if isinstance(input_attrs, dict) else {}
        inputs.append({
            "collection_key": _json_safe(key),
            "id": _json_safe(input_attrs.get("INPS_ID") or key),
            "name": _json_safe(input_attrs.get("INPS_Name")),
            "data_type": _json_safe(input_attrs.get("INPS_DataType")),
            "class": type(input_object).__name__,
            "attrs_call": input_attrs_call,
        })
    return {
        "collection_key": _json_safe(collection_key),
        "class": type(tool).__name__,
        "reg_id": _json_safe(attrs.get("TOOLS_RegID")),
        "name": _json_safe(attrs.get("TOOLS_Name")),
        "attrs_call": attrs_call,
        "input_list_call": inputs_call,
        "input_collection": input_structure,
        "inputs": inputs,
    }


def _comp_inventory(comp: Any, names: list[str], sources: list[str]) -> dict[str, Any]:
    raw_tools, call = _safe_call(comp, "GetToolList", False)
    entries, structure = _entries(raw_tools) if raw_tools is not None else ([], {"type": "NoneType", "keys": None, "length": 0, "error": None})
    return {
        "names": names,
        "sources": sources,
        "class": type(comp).__name__,
        "tool_list_call": call,
        "tool_collection": structure,
        "tools": [_tool_inventory(tool, key) for key, tool in entries],
    }


def _timeline_identity(timeline: Any) -> dict[str, Any]:
    name, _ = _safe_call(timeline, "GetName")
    uid, _ = _safe_call(timeline, "GetUniqueId")
    return {"name": str(name or ""), "unique_id": str(uid or "")}


def _track_geometry(timeline: Any, track: int) -> list[list[int]]:
    items, _ = _safe_call(timeline, "GetItemListInTrack", "video", track)
    rows = []
    for item in list(items or []):
        start, _ = _safe_call(item, "GetStart")
        end, _ = _safe_call(item, "GetEnd")
        duration, _ = _safe_call(item, "GetDuration")
        rows.append([int(start), int(end), int(duration)])
    return rows


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result = {
        "ok": False,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "classification": None,
        "mutation_counts": dict(MUTATION_COUNTS),
        "zero_mutation_claim": True,
        "failures": [],
    }
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        required = {
            "action": ACTION,
            "read_only": True,
            "zero_mutation": True,
            "project_mutation_permitted": False,
            "timeline_mutation_permitted": False,
            "caption_mutation_permitted": False,
            "fusion_mutation_permitted": False,
            "save_project": False,
            "delete_permitted": False,
            "replace_permitted": False,
            "retry_permitted": False,
        }
        if command.get("task") != TASK_ID or command.get("run_id") != run_id or command.get("mode") != MODE:
            raise ValueError("command_identity")
        if any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("read_only_authority")

        manager, _ = _safe_call(resolve, "GetProjectManager")
        project, _ = _safe_call(manager, "GetCurrentProject")
        project_name, _ = _safe_call(project, "GetName")
        if str(project_name or "") != str(payload.get("expected_project") or ""):
            raise ValueError(f"project_identity:{project_name}")
        timeline, _ = _safe_call(project, "GetCurrentTimeline")
        identity_before = _timeline_identity(timeline)
        expected_identity = {
            "name": str(payload.get("target_timeline_name") or ""),
            "unique_id": str(payload.get("target_timeline_uid") or ""),
        }
        if identity_before != expected_identity:
            raise ValueError(f"timeline_identity:{identity_before}")

        track = int(payload.get("caption_track_index") or 0)
        geometry_before = _track_geometry(timeline, track)
        if len(geometry_before) != int(payload.get("expected_caption_count") or 0):
            raise ValueError(f"caption_count:{len(geometry_before)}")
        wanted = [int(payload["caption_start"]), int(payload["caption_end"]), int(payload["caption_duration"])]
        items, _ = _safe_call(timeline, "GetItemListInTrack", "video", track)
        matches = []
        for item in list(items or []):
            start, _ = _safe_call(item, "GetStart")
            end, _ = _safe_call(item, "GetEnd")
            duration, _ = _safe_call(item, "GetDuration")
            if [int(start), int(end), int(duration)] == wanted:
                matches.append(item)
        if len(matches) != 1:
            raise ValueError(f"caption_geometry:{len(matches)}")
        item = matches[0]

        item_calls = {}
        for method in ("GetName", "GetStart", "GetEnd", "GetDuration", "GetProperty", "GetFusionCompCount", "GetFusionCompNameList", "GetFusionCompNames"):
            _, item_calls[method] = _safe_call(item, method)
        by_index, by_index_call = _safe_call(item, "GetFusionCompByIndex", 1)
        item_calls["GetFusionCompByIndex(1)"] = by_index_call

        raw_names = []
        for method in ("GetFusionCompNameList", "GetFusionCompNames"):
            value = item_calls[method]["value"]
            if isinstance(value, list):
                raw_names.extend(str(name) for name in value)
            elif isinstance(value, dict):
                raw_names.extend(str(name) for name in value.keys())
        names = list(dict.fromkeys(raw_names))
        discovered: list[dict[str, Any]] = []

        def add_comp(comp: Any, name: str, source: str) -> None:
            if comp is None:
                return
            for row in discovered:
                if row["object"] is comp:
                    if name and name not in row["names"]:
                        row["names"].append(name)
                    if source not in row["sources"]:
                        row["sources"].append(source)
                    return
            discovered.append({"object": comp, "names": [name] if name else [], "sources": [source]})

        add_comp(by_index, names[0] if names else "", "GetFusionCompByIndex(1)")
        named_calls = []
        for name in names:
            comp, call = _safe_call(item, "GetFusionCompByName", name)
            named_calls.append(call)
            add_comp(comp, name, "GetFusionCompByName")
        inventories = [_comp_inventory(row["object"], row["names"], row["sources"]) for row in discovered]
        tools = [tool for comp in inventories for tool in comp["tools"]]
        count = item_calls["GetFusionCompCount"]["value"]
        if not discovered and int(count or 0) == 0:
            classification = "CASE_A_NO_FUSION_COMP"
        elif any(str(tool.get("reg_id") or "").lower() in {"textplus", "text+"} for tool in tools):
            classification = "CASE_B_FUSION_COMP_TEXTPLUS_DISCOVERED"
        elif not discovered:
            classification = "CASE_B_FUSION_COMP_DISCOVERY_MISMATCH"
        else:
            classification = "CASE_C_DIFFERENT_CARRIER"

        identity_after = _timeline_identity(timeline)
        geometry_after = _track_geometry(timeline, track)
        if identity_after != identity_before or geometry_after != geometry_before:
            raise RuntimeError("resolve_state_drift")
        crash_state = None
        if payload.get("crash_state_check") is True:
            video_track_count, track_count_call = _safe_call(timeline, "GetTrackCount", "video")
            selected_rows = []
            for expected in list(payload.get("selected_geometries") or []):
                expected_geometry = [int(expected[0]), int(expected[1]), int(expected[2])]
                matched = [item for item in list(items or []) if [
                    int(_safe_call(item, "GetStart")[0]),
                    int(_safe_call(item, "GetEnd")[0]),
                    int(_safe_call(item, "GetDuration")[0]),
                ] == expected_geometry]
                properties, properties_call = _safe_call(matched[0], "GetProperty") if len(matched) == 1 else (None, {})
                comp_count, comp_count_call = _safe_call(matched[0], "GetFusionCompCount") if len(matched) == 1 else (None, {})
                selected_rows.append({
                    "geometry": expected_geometry,
                    "match_count": len(matched),
                    "opacity": properties.get("Opacity") if isinstance(properties, dict) else None,
                    "fusion_comp_count": comp_count,
                    "property_call": properties_call,
                    "comp_count_call": comp_count_call,
                })
            extra_tracks = []
            for extra_track in range(track + 1, int(video_track_count or 0) + 1):
                extra_items, extra_call = _safe_call(timeline, "GetItemListInTrack", "video", extra_track)
                extra_tracks.append({
                    "track_index": extra_track,
                    "item_count": len(list(extra_items or [])),
                    "items": [{
                        "name": _safe_call(item, "GetName")[0],
                        "start": _safe_call(item, "GetStart")[0],
                        "end": _safe_call(item, "GetEnd")[0],
                        "duration": _safe_call(item, "GetDuration")[0],
                        "fusion_comp_count": _safe_call(item, "GetFusionCompCount")[0],
                    } for item in list(extra_items or [])],
                    "call": extra_call,
                })
            expected_track_count = int(payload.get("expected_video_track_count") or track)
            clean = bool(
                int(video_track_count or 0) == expected_track_count
                and len(selected_rows) == int(payload.get("expected_selected_caption_count") or 0)
                and all(row["match_count"] == 1 and float(row["opacity"]) == 100.0 and int(row["fusion_comp_count"] or 0) == 0 for row in selected_rows)
                and not extra_tracks
            )
            crash_state = {
                "classification": "CRASH_STATE_CLEAN" if clean else "PARTIAL_STATE_PRESENT",
                "video_track_count": video_track_count,
                "video_track_count_call": track_count_call,
                "expected_video_track_count": expected_track_count,
                "selected_captions": selected_rows,
                "extra_tracks": extra_tracks,
                "clean": clean,
            }
        result.update({
            "ok": True,
            "classification": classification,
            "project_name": str(project_name),
            "timeline_identity_before": identity_before,
            "timeline_identity_after": identity_after,
            "caption_track_index": track,
            "caption_count": len(geometry_before),
            "caption_geometry": wanted,
            "caption_item_calls": item_calls,
            "fusion_comp_by_name_calls": named_calls,
            "discoverable_comp_names": names,
            "compositions": inventories,
            "timeline_identity_unchanged": True,
            "caption_geometry_unchanged": True,
            "crash_state": crash_state,
        })
    except Exception as exc:
        result["failures"] = [f"{type(exc).__name__}: {exc}"]
    return result
