"""Two-caption live Resolve probe using media-backed carriers plus source Fusion comps.

The probe duplicates the protected source timeline, removes its generated caption
items, appends two media-backed carriers at the calibrated COME/they lifecycle
windows and lanes, applies the protected source Fusion compositions, saves and
reacquires all handles, and leaves the duplicate timeline for visual approval on
PASS. On any failure the duplicate timeline is deleted and the original current
timeline is restored.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

TASK_ID = "DZSQH7AUHJT_STEP_3D_EXISTING_TEXTPLUS_CLONE_PROBE_V1"
MODE = "STEP_3D_EXISTING_TEXTPLUS_CLONE_PROBE"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3D_existing_textplus_clone_probe.py"
BRIDGE_RELATIVE_PATH = "resolve_workspace/VC_Agent_Bridge.py"
POSITION_PLAN_RELATIVE_PATH = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_position_full_plan_step_3B_5B.json"
ANIMATION_PLAN_RELATIVE_PATH = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_animation_step_3C_source_targets.json"
LIFECYCLE_PLAN_RELATIVE_PATH = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_lifecycle_authority_step_3D_calibrated.json"
SOURCE_REPORT_RELATIVE_PATH = "data/DZsqH7auhjt/davinci/DZsqH7auhjt_textplus_full_timeline_report.json"
ACCEPTED_STATE_RELATIVE_PATH = ".agent/state/latest_accepted.json"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_full"
CAPTION_PREFIX = "VC_TEXTPLUS_"
EXPECTED_SOURCE_CAPTION_COUNT = 116
EXPECTED_FPS = 24.0

TARGETS: Tuple[Dict[str, Any], ...] = (
    {
        "cue_id": "sub_052",
        "name": "VC_TEXTPLUS_0052_sub_052",
        "text": "COME",
        "source_range": [430, 434],
        "target_range": [430, 452],
        "target_track": 3,
        "center_targets": [
            {"frame": 0, "value": [0.4324, 0.6292]},
            {"frame": 3, "value": [0.5, 0.6276]},
        ],
    },
    {
        "cue_id": "sub_054",
        "name": "VC_TEXTPLUS_0054_sub_054",
        "text": "they",
        "source_range": [439, 443],
        "target_range": [437, 452],
        "target_track": 5,
        "center_targets": [
            {"frame": 0, "value": [0.494, 0.532]},
        ],
    },
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def normalized_sha256(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def compact_exception(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return repr(value)


def direct_call(obj: Any, method_name: str, *args: Any) -> Tuple[Any, Dict[str, Any]]:
    available = bool(obj is not None and callable(getattr(obj, method_name, None)))
    row: Dict[str, Any] = {
        "method": method_name,
        "available": available,
        "args": json_safe(args),
        "ok": False,
        "returned_type": None,
        "returned_repr": None,
        "error": None,
    }
    if not available:
        row["error"] = "method_missing"
        return None, row
    try:
        value = getattr(obj, method_name)(*args)
        row["returned_type"] = type(value).__name__ if value is not None else None
        row["returned_repr"] = repr(value)
        row["ok"] = value is not False and value is not None
        return value, row
    except BaseException as exc:
        row["error"] = compact_exception(exc)
        row["traceback"] = traceback.format_exc()
        return None, row


def safe_value(obj: Any, method_name: str, *args: Any, default: Any = None) -> Any:
    try:
        method = getattr(obj, method_name, None)
        if not callable(method):
            return default
        value = method(*args)
        return default if value is None else value
    except BaseException:
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def relative_path(root: Path, value: Any) -> Path:
    candidate = Path(str(value).replace("\\", "/"))
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    resolved.relative_to(root.resolve())
    return resolved


def verify_source_contract(root: Path, command: Dict[str, Any]) -> Dict[str, Any]:
    contract = command.get("source_contract")
    if not isinstance(contract, dict):
        raise ValueError("source_contract")
    if contract.get("algorithm") != SOURCE_HASH_ALGORITHM:
        raise ValueError("source_hash_algorithm")
    hashes = contract.get("hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("source_hashes")
    rows = []
    for relative, expected in sorted(hashes.items()):
        path = root / str(relative)
        if not path.is_file():
            raise ValueError(f"source_missing:{relative}")
        actual = normalized_sha256(path)
        matched = actual == expected
        rows.append({"path": relative, "expected": expected, "actual": actual, "matched": matched})
        if not matched:
            raise ValueError(f"source_hash:{relative}")
    return {
        "version": contract.get("version"),
        "algorithm": SOURCE_HASH_ALGORITHM,
        "verified_count": len(rows),
        "rows": rows,
    }


def get_project(resolve: Any) -> Tuple[Any, Any, Any, List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    project_manager, row = direct_call(resolve, "GetProjectManager")
    rows.append(row)
    if project_manager is None:
        raise RuntimeError("project_manager")
    project, row = direct_call(project_manager, "GetCurrentProject")
    rows.append(row)
    if project is None:
        raise RuntimeError("project")
    media_pool, row = direct_call(project, "GetMediaPool")
    rows.append(row)
    if media_pool is None:
        raise RuntimeError("media_pool")
    return project_manager, project, media_pool, rows


def timeline_count(project: Any) -> int:
    return as_int(safe_value(project, "GetTimelineCount", default=0), 0)


def timeline_name(timeline: Any) -> str:
    return str(safe_value(timeline, "GetName", default="") or "")


def timeline_unique_id(timeline: Any) -> str:
    return str(safe_value(timeline, "GetUniqueId", default="") or "")


def find_timeline(project: Any, name: str) -> Any:
    for index in range(1, timeline_count(project) + 1):
        timeline = safe_value(project, "GetTimelineByIndex", index, default=None)
        if timeline is not None and timeline_name(timeline) == name:
            return timeline
    return None


def project_timeline_snapshot(project: Any) -> Dict[str, Any]:
    current = safe_value(project, "GetCurrentTimeline", default=None)
    rows = []
    for index in range(1, timeline_count(project) + 1):
        timeline = safe_value(project, "GetTimelineByIndex", index, default=None)
        if timeline is not None:
            rows.append({"name": timeline_name(timeline), "unique_id": timeline_unique_id(timeline)})
    return {
        "count": len(rows),
        "current": {
            "name": timeline_name(current) if current is not None else None,
            "unique_id": timeline_unique_id(current) if current is not None else None,
        },
        "timelines": rows,
    }


def track_count(timeline: Any, track_type: str) -> int:
    return as_int(safe_value(timeline, "GetTrackCount", track_type, default=0), 0)


def track_items(timeline: Any, track_type: str, track_index: int) -> List[Any]:
    value = safe_value(timeline, "GetItemListInTrack", track_type, track_index, default=[])
    return list(value or [])


def item_name(item: Any) -> str:
    return str(safe_value(item, "GetName", default="") or "")


def item_start(item: Any) -> int:
    return as_int(safe_value(item, "GetStart", default=0), 0)


def item_end(item: Any) -> int:
    return as_int(safe_value(item, "GetEnd", default=0), 0)


def item_duration(item: Any) -> int:
    return as_int(safe_value(item, "GetDuration", default=item_end(item) - item_start(item)), 0)


def item_unique_id(item: Any) -> str:
    return str(safe_value(item, "GetUniqueId", default="") or "")


def all_video_items(timeline: Any) -> List[Tuple[int, Any]]:
    rows: List[Tuple[int, Any]] = []
    for track_index in range(1, track_count(timeline, "video") + 1):
        for item in track_items(timeline, "video", track_index):
            rows.append((track_index, item))
    return rows


def item_summary(track_index: int, item: Any) -> Dict[str, Any]:
    media_pool_item = safe_value(item, "GetMediaPoolItem", default=None)
    return {
        "name": item_name(item),
        "unique_id": item_unique_id(item),
        "track_index": track_index,
        "start": item_start(item),
        "end": item_end(item),
        "duration": item_duration(item),
        "fusion_comp_count": as_int(safe_value(item, "GetFusionCompCount", default=0), 0),
        "media_pool_item_name": str(safe_value(media_pool_item, "GetName", default="") or "") if media_pool_item else None,
    }


def find_named_item(timeline: Any, name: str) -> Tuple[Optional[int], Any]:
    matches = [(track, item) for track, item in all_video_items(timeline) if item_name(item) == name]
    if len(matches) != 1:
        return None, None
    return matches[0]


def caption_items(timeline: Any) -> List[Tuple[int, Any]]:
    return [(track, item) for track, item in all_video_items(timeline) if item_name(item).startswith(CAPTION_PREFIX)]


def delete_items(timeline: Any, items: Iterable[Any]) -> Dict[str, Any]:
    item_list = list(items)
    value, row = direct_call(timeline, "DeleteClips", item_list, False)
    return {"requested_count": len(item_list), "call": row, "ok": bool(value)}


def ensure_video_tracks(timeline: Any, minimum_count: int) -> Dict[str, Any]:
    attempts = []
    while track_count(timeline, "video") < minimum_count:
        before = track_count(timeline, "video")
        value, row = direct_call(timeline, "AddTrack", "video")
        row["before_count"] = before
        time.sleep(0.10)
        row["after_count"] = track_count(timeline, "video")
        row["verified"] = row["after_count"] > before
        attempts.append(row)
        if not value or not row["verified"]:
            break
    return {
        "requested_minimum": minimum_count,
        "final_count": track_count(timeline, "video"),
        "attempts": attempts,
        "ok": track_count(timeline, "video") >= minimum_count,
    }


def set_item_name(item: Any, name: str) -> Dict[str, Any]:
    attempts = []
    for method_name in ("SetName", "SetClipName"):
        value, row = direct_call(item, method_name, name)
        attempts.append(row)
        if value and item_name(item) == name:
            return {"ok": True, "attempts": attempts, "readback": item_name(item)}
    value, row = direct_call(item, "SetProperty", "Name", name)
    attempts.append(row)
    return {"ok": bool(value and item_name(item) == name), "attempts": attempts, "readback": item_name(item)}


def get_comp(item: Any) -> Any:
    count = as_int(safe_value(item, "GetFusionCompCount", default=0), 0)
    if count < 1:
        return None
    comp = safe_value(item, "GetFusionCompByIndex", 1, default=None)
    if comp is not None:
        return comp
    names = list(safe_value(item, "GetFusionCompNameList", default=[]) or [])
    if names:
        comp = safe_value(item, "GetFusionCompByName", names[0], default=None)
        if comp is not None:
            return comp
        return safe_value(item, "LoadFusionCompByName", names[0], default=None)
    return None


def get_text_tool(comp: Any) -> Any:
    if comp is None:
        return None
    tools = safe_value(comp, "GetToolList", False, "TextPlus", default={}) or {}
    if isinstance(tools, dict) and tools:
        return next(iter(tools.values()))
    tools = safe_value(comp, "GetToolList", False, default={}) or {}
    if isinstance(tools, dict):
        for tool in tools.values():
            attrs = safe_value(tool, "GetAttrs", default={}) or {}
            if str(attrs.get("TOOLS_RegID") or "") == "TextPlus":
                return tool
    return None


def find_input(tool: Any, input_name: str) -> Any:
    value = safe_value(tool, "FindInput", input_name, default=None)
    if value is not None:
        return value
    try:
        value = getattr(tool, input_name)
        if value is not None:
            return value
    except BaseException:
        pass
    inputs = safe_value(tool, "GetInputList", default={}) or {}
    if isinstance(inputs, dict):
        for input_object in inputs.values():
            attrs = safe_value(input_object, "GetAttrs", default={}) or {}
            if attrs.get("INPS_ID") == input_name or attrs.get("INPS_Name") == input_name:
                return input_object
    return None


def read_input(tool: Any, input_name: str, frame: int) -> Any:
    try:
        value = tool.GetInput(input_name, frame)
        if value is not None:
            return value
    except BaseException:
        pass
    input_object = find_input(tool, input_name)
    if input_object is not None:
        try:
            return input_object[frame]
        except BaseException:
            pass
    return None


def normalize_point(value: Any) -> Optional[List[float]]:
    if isinstance(value, dict):
        x = value.get(1, value.get("1", value.get("x", value.get("X"))))
        y = value.get(2, value.get("2", value.get("y", value.get("Y"))))
        if x is not None and y is not None:
            return [as_float(x), as_float(y)]
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return [as_float(value[0]), as_float(value[1])]
    return None


def point_matches(actual: Any, expected: List[float], tolerance: float = 0.0025) -> bool:
    normalized = normalize_point(actual)
    if normalized is None:
        return False
    return all(abs(normalized[index] - expected[index]) <= tolerance for index in (0, 1))


def text_readback(tool: Any) -> str:
    for input_name in ("StyledText", "InputStyledText", "Text"):
        value = read_input(tool, input_name, 0)
        if isinstance(value, str) and value:
            return value
        if value is not None:
            text = str(value)
            if text and "BlackmagicFusion" not in text:
                return text
    return ""


def visual_readback(item: Any, spec: Dict[str, Any]) -> Dict[str, Any]:
    comp = get_comp(item)
    text_tool = get_text_tool(comp)
    actual_text = text_readback(text_tool) if text_tool is not None else ""
    center_rows = []
    for target in spec["center_targets"]:
        actual = read_input(text_tool, "Center", int(target["frame"])) if text_tool is not None else None
        center_rows.append({
            "frame": int(target["frame"]),
            "expected": target["value"],
            "actual": json_safe(actual),
            "matched": point_matches(actual, target["value"]),
        })
    return {
        "fusion_comp_count": as_int(safe_value(item, "GetFusionCompCount", default=0), 0),
        "comp_available": comp is not None,
        "text_tool_available": text_tool is not None,
        "expected_text": spec["text"],
        "actual_text": actual_text,
        "text_matched": actual_text.strip() == str(spec["text"]).strip(),
        "center_targets": center_rows,
        "center_targets_matched": all(row["matched"] for row in center_rows),
    }


def source_item_snapshot(timeline: Any, specs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    for spec in specs:
        track, item = find_named_item(timeline, spec["name"])
        if item is None:
            rows.append({"name": spec["name"], "found": False})
            continue
        rows.append({
            "name": spec["name"],
            "found": True,
            "summary": item_summary(int(track or 0), item),
            "visual": visual_readback(item, spec),
        })
    return {"rows": rows}


def choose_carrier_source(timeline: Any, duration: int) -> Dict[str, Any]:
    attempts = []
    for item in track_items(timeline, "video", 1):
        media_pool_item = safe_value(item, "GetMediaPoolItem", default=None)
        if media_pool_item is None:
            continue
        item_duration_value = item_duration(item)
        left_offset = max(0, as_int(safe_value(item, "GetLeftOffset", default=0), 0))
        row = {
            "item_name": item_name(item),
            "duration": item_duration_value,
            "left_offset": left_offset,
            "media_pool_item_name": str(safe_value(media_pool_item, "GetName", default="") or ""),
        }
        attempts.append(row)
        if item_duration_value >= duration:
            return {
                "ok": True,
                "item": item,
                "media_pool_item": media_pool_item,
                "source_start": left_offset,
                "attempts": attempts,
            }
    return {"ok": False, "attempts": attempts, "error": f"carrier_source:{duration}"}


def item_track_index(timeline: Any, item: Any) -> Optional[int]:
    wanted_uid = item_unique_id(item)
    for track_index, candidate in all_video_items(timeline):
        candidate_uid = item_unique_id(candidate)
        if wanted_uid and candidate_uid == wanted_uid:
            return track_index
        if candidate is item:
            return track_index
    return None


def append_carriers(media_pool: Any, timeline: Any, source: Dict[str, Any], specs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    before_ids = {item_unique_id(item) for _, item in all_video_items(timeline) if item_unique_id(item)}
    clip_infos = []
    for spec in specs:
        start, end = [int(value) for value in spec["target_range"]]
        duration = end - start
        clip_infos.append({
            "mediaPoolItem": source["media_pool_item"],
            "startFrame": int(source["source_start"]),
            "endFrame": int(source["source_start"]) + duration - 1,
            "mediaType": 1,
            "trackIndex": int(spec["target_track"]),
            "recordFrame": start,
        })
    returned, call = direct_call(media_pool, "AppendToTimeline", clip_infos)
    time.sleep(0.25)
    returned_items = list(returned) if isinstance(returned, (list, tuple)) else []
    detected = [item for _, item in all_video_items(timeline) if item_unique_id(item) and item_unique_id(item) not in before_ids]
    items = returned_items if len(returned_items) == len(clip_infos) else detected
    rows = []
    assigned = []
    remaining = list(items)
    for spec in specs:
        target_start, target_end = [int(value) for value in spec["target_range"]]
        match_index = None
        for index, item in enumerate(remaining):
            track = item_track_index(timeline, item)
            if (
                track == int(spec["target_track"])
                and item_start(item) == target_start
                and item_duration(item) == target_end - target_start
            ):
                match_index = index
                break
        if match_index is None:
            rows.append({"cue_id": spec["cue_id"], "matched": False})
            continue
        item = remaining.pop(match_index)
        assigned.append((spec, item))
        name_write = set_item_name(item, spec["name"])
        rows.append({
            "cue_id": spec["cue_id"],
            "matched": True,
            "summary": item_summary(int(spec["target_track"]), item),
            "name_write": name_write,
            "ok": name_write.get("ok") is True,
        })
    return {
        "call": call,
        "clip_infos": [{key: (str(value) if key == "mediaPoolItem" else value) for key, value in row.items()} for row in clip_infos],
        "returned_count": len(returned_items),
        "detected_count": len(detected),
        "assigned_count": len(assigned),
        "rows": rows,
        "assigned": assigned,
        "ok": len(assigned) == len(clip_infos) and all(row.get("ok") for row in rows),
    }


def wait_for_comp(item: Any, timeout_seconds: float = 2.0, poll_seconds: float = 0.10) -> Tuple[Any, List[Dict[str, Any]]]:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    rows = []
    while True:
        comp = get_comp(item)
        rows.append({
            "elapsed_seconds": round(max(0.0, timeout_seconds - max(0.0, deadline - time.monotonic())), 4),
            "count": as_int(safe_value(item, "GetFusionCompCount", default=0), 0),
            "comp_available": comp is not None,
        })
        if comp is not None:
            return comp, rows
        if time.monotonic() >= deadline:
            return None, rows
        time.sleep(max(0.02, poll_seconds))


def apply_source_comp(source_item: Any, target_item: Any, comp_path: Path) -> Dict[str, Any]:
    before_count = as_int(safe_value(target_item, "GetFusionCompCount", default=0), 0)
    imported, import_call = direct_call(target_item, "ImportFusionComp", str(comp_path))
    comp, import_poll = wait_for_comp(target_item)
    if imported is not None:
        comp = imported
    strategy = "ImportFusionComp"
    fallback = None
    if comp is None:
        target_comp, add_call = direct_call(target_item, "AddFusionComp")
        comp, add_poll = wait_for_comp(target_item)
        if target_comp is not None:
            comp = target_comp
        fallback = {"add_call": add_call, "add_poll": add_poll, "copy": None, "paste": None}
        if comp is not None:
            source_comp = get_comp(source_item)
            settings, copy_call = direct_call(source_comp, "CopySettings")
            fallback["copy"] = copy_call
            pasted, paste_call = direct_call(comp, "Paste", settings) if settings is not None else (None, {"error": "copy_settings_missing"})
            fallback["paste"] = paste_call
            if pasted or paste_call.get("ok"):
                strategy = "AddFusionComp_CopySettings_Paste"
    after_count = as_int(safe_value(target_item, "GetFusionCompCount", default=0), 0)
    return {
        "strategy": strategy,
        "before_count": before_count,
        "after_count": after_count,
        "import_call": import_call,
        "import_poll": import_poll,
        "fallback": fallback,
        "comp_available": get_comp(target_item) is not None,
        "ok": get_comp(target_item) is not None,
    }


def save_project(project_manager: Any) -> Dict[str, Any]:
    value, row = direct_call(project_manager, "SaveProject")
    return {"call": row, "success": bool(value)}


def stable_source_contract(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for row in snapshot.get("rows") or []:
        summary = row.get("summary") or {}
        visual = row.get("visual") or {}
        rows.append({
            "name": row.get("name"),
            "found": row.get("found") is True,
            "unique_id": summary.get("unique_id"),
            "track_index": summary.get("track_index"),
            "start": summary.get("start"),
            "end": summary.get("end"),
            "duration": summary.get("duration"),
            "fusion_comp_count": summary.get("fusion_comp_count"),
            "text_matched": visual.get("text_matched") is True,
            "center_targets_matched": visual.get("center_targets_matched") is True,
        })
    return rows


def source_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> bool:
    return stable_source_contract(before) == stable_source_contract(after)


def cleanup_probe(resolve: Any, probe_name: str, original_name: str, root: Path, accepted_hash: str) -> Dict[str, Any]:
    cleanup: Dict[str, Any] = {"attempted": True, "started_at": utc_now(), "errors": []}
    try:
        project_manager, project, media_pool, rows = get_project(resolve)
        cleanup["resolve_calls"] = rows
        original = find_timeline(project, original_name)
        if original is not None:
            value, row = direct_call(project, "SetCurrentTimeline", original)
            cleanup["restore_original"] = row
            if not value:
                cleanup["errors"].append("restore_original")
        probe = find_timeline(project, probe_name)
        cleanup["probe_found"] = probe is not None
        if probe is not None:
            value, row = direct_call(media_pool, "DeleteTimelines", [probe])
            cleanup["delete_probe"] = row
            if not value:
                cleanup["errors"].append("delete_probe")
        cleanup["probe_deleted"] = find_timeline(project, probe_name) is None
        save = save_project(project_manager)
        cleanup["save_cleanup"] = save
        if not save["success"]:
            cleanup["errors"].append("save_cleanup")
    except BaseException as exc:
        cleanup["errors"].append(compact_exception(exc))
        cleanup["traceback"] = traceback.format_exc()
    accepted_path = root / ACCEPTED_STATE_RELATIVE_PATH
    cleanup["accepted_state_unchanged"] = accepted_path.is_file() and raw_sha256(accepted_path) == accepted_hash
    cleanup["finished_at"] = utc_now()
    cleanup["ok"] = not cleanup["errors"] and cleanup.get("probe_deleted") is True and cleanup.get("accepted_state_unchanged") is True
    return cleanup


def run(resolve: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    root = repository_root()
    command = context.get("command") if isinstance(context, dict) else None
    if not isinstance(command, dict):
        raise ValueError("command")
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    if not run_id:
        raise ValueError("run_id")
    if command.get("task_id") != TASK_ID or command.get("mode") != MODE:
        raise ValueError("command_identity")
    report_dir = relative_path(root, command.get("artifacts_dir"))
    report_dir.mkdir(parents=True, exist_ok=True)
    accepted_hash = str(command.get("accepted_state_sha256") or "")
    probe = command.get("probe")
    if not isinstance(probe, dict):
        raise ValueError("probe")
    probe_name = str(probe.get("timeline_name") or "")
    if not probe_name:
        raise ValueError("probe_timeline_name")

    report: Dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "ok": False,
        "started_at": utc_now(),
        "probe_timeline_name": probe_name,
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "failures": [],
        "save_call_count": 0,
        "probe_timeline_kept": False,
        "visual_review_required": False,
    }
    original_name = ""
    duplicate_created = False

    try:
        source_contract = verify_source_contract(root, command)
        report["source_contract_verified_count"] = source_contract["verified_count"]
        write_json(report_dir / "source_contract_verification.json", source_contract)

        accepted_path = root / ACCEPTED_STATE_RELATIVE_PATH
        if not accepted_path.is_file() or raw_sha256(accepted_path) != accepted_hash:
            raise RuntimeError("accepted_state")

        project_manager, project, media_pool, resolve_calls = get_project(resolve)
        before_timelines = project_timeline_snapshot(project)
        original_name = str((before_timelines.get("current") or {}).get("name") or "")
        source = find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        source_unique_id = timeline_unique_id(source)
        source_caption_rows = caption_items(source)
        if len(source_caption_rows) != EXPECTED_SOURCE_CAPTION_COUNT:
            raise RuntimeError(f"source_caption_count:{len(source_caption_rows)}")

        source_before = source_item_snapshot(source, TARGETS)
        if any(not row.get("found") for row in source_before["rows"]):
            raise RuntimeError("source_target_missing")
        for spec, row in zip(TARGETS, source_before["rows"]):
            summary = row["summary"]
            if [summary["start"], summary["end"]] != spec["source_range"]:
                raise RuntimeError(f"source_range:{spec['cue_id']}")
            if not row["visual"]["text_matched"] or not row["visual"]["center_targets_matched"]:
                raise RuntimeError(f"source_visual:{spec['cue_id']}")

        carrier_source = choose_carrier_source(source, max(spec["target_range"][1] - spec["target_range"][0] for spec in TARGETS))
        if not carrier_source.get("ok"):
            raise RuntimeError("carrier_source")

        preflight = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "checked_at": utc_now(),
            "resolve_calls": resolve_calls,
            "before_timelines": before_timelines,
            "original_timeline_name": original_name,
            "source_timeline": {"name": SOURCE_TIMELINE_NAME, "unique_id": source_unique_id},
            "source_caption_count": len(source_caption_rows),
            "source_targets": source_before,
            "carrier_source": {key: json_safe(value) for key, value in carrier_source.items() if key not in {"item", "media_pool_item"}},
            "targets": TARGETS,
            "accepted_state_sha256": accepted_hash,
        }
        write_json(report_dir / "probe_preflight.json", preflight)

        export_dir = report_dir / "source_comp_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        export_rows = []
        source_items: Dict[str, Any] = {}
        for spec in TARGETS:
            track, source_item = find_named_item(source, spec["name"])
            if source_item is None:
                raise RuntimeError(f"source_item:{spec['cue_id']}")
            source_items[spec["cue_id"]] = source_item
            comp_path = export_dir / f"{spec['cue_id']}.comp"
            value, row = direct_call(source_item, "ExportFusionComp", str(comp_path), 1)
            file_ok = bool(value and comp_path.is_file() and comp_path.stat().st_size > 0)
            export_rows.append({
                "cue_id": spec["cue_id"],
                "name": spec["name"],
                "track": track,
                "call": row,
                "path": str(comp_path),
                "size": comp_path.stat().st_size if comp_path.is_file() else 0,
                "sha256": raw_sha256(comp_path) if file_ok else None,
                "ok": file_ok,
            })
            if not file_ok:
                raise RuntimeError(f"source_comp_export:{spec['cue_id']}")
        write_json(report_dir / "source_comp_exports.json", {"rows": export_rows, "exported_count": len(export_rows), "ok": all(row["ok"] for row in export_rows)})

        value, duplicate_call = direct_call(source, "DuplicateTimeline", probe_name)
        duplicate = value if value is not None else find_timeline(project, probe_name)
        if duplicate is None:
            raise RuntimeError("duplicate_timeline")
        duplicate_created = True
        value, set_current_call = direct_call(project, "SetCurrentTimeline", duplicate)
        if not value:
            raise RuntimeError("select_duplicate")

        duplicate_before_captions = caption_items(duplicate)
        deletion = delete_items(duplicate, [item for _, item in duplicate_before_captions])
        time.sleep(0.20)
        remaining_captions = caption_items(duplicate)
        if not deletion.get("ok") or remaining_captions:
            raise RuntimeError(f"caption_cleanup:{len(remaining_captions)}")

        track_setup = ensure_video_tracks(duplicate, 5)
        if not track_setup.get("ok"):
            raise RuntimeError("video_tracks")

        duplicate_evidence = {
            "duplicate_call": duplicate_call,
            "set_current_call": set_current_call,
            "duplicate_name": timeline_name(duplicate),
            "duplicate_unique_id": timeline_unique_id(duplicate),
            "caption_count_before_delete": len(duplicate_before_captions),
            "caption_delete": deletion,
            "caption_count_after_delete": len(remaining_captions),
            "track_setup": track_setup,
        }
        write_json(report_dir / "duplicate_timeline_setup.json", duplicate_evidence)

        append = append_carriers(media_pool, duplicate, carrier_source, TARGETS)
        append_artifact = {key: value for key, value in append.items() if key != "assigned"}
        write_json(report_dir / "carrier_append.json", json_safe(append_artifact))
        if not append.get("ok"):
            raise RuntimeError("carrier_append")

        clone_rows = []
        for spec, target_item in append["assigned"]:
            export_path = export_dir / f"{spec['cue_id']}.comp"
            clone = apply_source_comp(source_items[spec["cue_id"]], target_item, export_path)
            visual = visual_readback(target_item, spec)
            row = {
                "cue_id": spec["cue_id"],
                "name": spec["name"],
                "target_summary": item_summary(int(spec["target_track"]), target_item),
                "clone": clone,
                "visual": visual,
                "ok": bool(clone.get("ok") and visual.get("text_matched") and visual.get("center_targets_matched")),
            }
            clone_rows.append(row)
            write_json(report_dir / "comp_clone_progress.json", {"completed_count": sum(1 for item in clone_rows if item["ok"]), "rows": clone_rows})
            if not row["ok"]:
                raise RuntimeError(f"comp_clone:{spec['cue_id']}")
        write_json(report_dir / "comp_clone_application.json", {"rows": clone_rows, "completed_count": len(clone_rows), "ok": True})

        first_save = save_project(project_manager)
        report["save_call_count"] += 1 if first_save.get("success") else 0
        if not first_save.get("success"):
            raise RuntimeError("save_probe")

        project_manager, project, media_pool, reacquire_calls = get_project(resolve)
        duplicate_after = find_timeline(project, probe_name)
        source_after = find_timeline(project, SOURCE_TIMELINE_NAME)
        if duplicate_after is None or source_after is None:
            raise RuntimeError("persistent_timeline_reacquire")
        target_rows = []
        for spec in TARGETS:
            track, item = find_named_item(duplicate_after, spec["name"])
            if item is None:
                target_rows.append({"cue_id": spec["cue_id"], "found": False})
                continue
            summary = item_summary(int(track or 0), item)
            visual = visual_readback(item, spec)
            expected_start, expected_end = spec["target_range"]
            timing_ok = bool(
                track == spec["target_track"]
                and summary["start"] == expected_start
                and summary["duration"] == expected_end - expected_start
                and summary["end"] in {expected_end, expected_end - 1}
            )
            target_rows.append({
                "cue_id": spec["cue_id"],
                "found": True,
                "summary": summary,
                "visual": visual,
                "timing_ok": timing_ok,
                "ok": bool(timing_ok and visual["text_matched"] and visual["center_targets_matched"] and visual["comp_available"]),
            })

        source_after_snapshot = source_item_snapshot(source_after, TARGETS)
        source_protected = bool(
            timeline_unique_id(source_after) == source_unique_id
            and source_unchanged(source_before, source_after_snapshot)
        )
        accepted_unchanged = accepted_path.is_file() and raw_sha256(accepted_path) == accepted_hash
        persistent = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "checked_at": utc_now(),
            "reacquire_calls": reacquire_calls,
            "targets": target_rows,
            "targets_ok": all(row.get("ok") for row in target_rows) and len(target_rows) == len(TARGETS),
            "source_before": source_before,
            "source_after": source_after_snapshot,
            "source_timeline_unchanged": source_protected,
            "accepted_state_unchanged": accepted_unchanged,
            "probe_timeline_kept": True,
            "save": first_save,
        }
        write_json(report_dir / "persistent_readback.json", persistent)
        if not persistent["targets_ok"]:
            raise RuntimeError("persistent_target_readback")
        if not source_protected:
            raise RuntimeError("source_timeline_changed")
        if not accepted_unchanged:
            raise RuntimeError("accepted_state_changed")

        report.update({
            "ok": True,
            "finished_at": utc_now(),
            "source_contract_verified_count": source_contract["verified_count"],
            "source_comp_export_count": len(export_rows),
            "carrier_append_count": append["assigned_count"],
            "comp_clone_count": len(clone_rows),
            "target_readback_count": sum(1 for row in target_rows if row.get("ok")),
            "source_timeline_unchanged": source_protected,
            "accepted_state_unchanged": accepted_unchanged,
            "probe_timeline_kept": True,
            "probe_timeline_unique_id": timeline_unique_id(duplicate_after),
            "visual_review_required": True,
            "visual_review_window": [430, 452],
            "visual_review_instruction": f"Open {probe_name} and review frames 430-452 for COME slide/persistence and independent they placement.",
        })
        write_json(report_dir / "probe_result.json", report)
        return report

    except BaseException as exc:
        failure = compact_exception(exc)
        report["failures"].append(failure)
        report["traceback"] = traceback.format_exc()
        cleanup = cleanup_probe(resolve, probe_name, original_name or SOURCE_TIMELINE_NAME, root, accepted_hash) if duplicate_created else {
            "attempted": False,
            "probe_deleted": True,
            "accepted_state_unchanged": (root / ACCEPTED_STATE_RELATIVE_PATH).is_file() and raw_sha256(root / ACCEPTED_STATE_RELATIVE_PATH) == accepted_hash,
            "ok": True,
        }
        if cleanup.get("save_cleanup", {}).get("success"):
            report["save_call_count"] += 1
        report.update({
            "ok": False,
            "finished_at": utc_now(),
            "cleanup": cleanup,
            "probe_timeline_kept": False,
            "visual_review_required": False,
            "accepted_state_unchanged": cleanup.get("accepted_state_unchanged"),
        })
        write_json(report_dir / "probe_cleanup.json", cleanup)
        write_json(report_dir / "probe_result.json", report)
        return report
