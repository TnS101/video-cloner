"""Live Resolve capability probe for native Text+ title insertion.

This probe duplicates the protected source timeline, removes generated captions,
opens the Edit page, isolates one unlocked target video track, and invokes
Timeline.InsertFusionTitleIntoTimeline("Text+") exactly once. It accepts the
returned TimelineItem or, when Resolve returns None after creating the title,
detects exactly one new item from the timeline delta. It then writes text and two
Center keyframes, saves, reacquires and verifies persistent readback, deletes the
temporary timeline, restores the original timeline, and restores the original
Resolve page.

The protected source timeline is never modified. The temporary timeline is
deleted after both PASS and FAIL. One published command permits exactly one
Workspace > Scripts > VC_Run_Agent_Task invocation.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

TASK_ID = "DZSQH7AUHJT_STEP_3D_NATIVE_TEXTPLUS_TITLE_PROBE_V2"
MODE = "STEP_3D_NATIVE_TEXTPLUS_TITLE_PROBE"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3D_native_textplus_title_probe.py"
BRIDGE_RELATIVE_PATH = "resolve_workspace/VC_Agent_Bridge.py"
ACCEPTED_STATE_RELATIVE_PATH = ".agent/state/latest_accepted.json"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
ACCEPTED_HASH_ALGORITHM = "sha256_canonical_json"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_full"
CAPTION_PREFIX = "VC_TEXTPLUS_"
EXPECTED_SOURCE_CAPTION_COUNT = 116
EXPECTED_FPS = 24
TARGET_FRAME = 430
TARGET_TRACK = 3
TITLE_NAME = "Text+"
PROBE_TEXT = "VC_NATIVE_TEXTPLUS_PROBE"
PROBE_ITEM_NAME = "VC_NATIVE_TEXTPLUS_PROBE_ITEM"
CENTER_KEYFRAMES: Tuple[Tuple[int, List[float]], ...] = (
    (0, [0.4324, 0.6292]),
    (3, [0.5000, 0.6276]),
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def normalized_sha256(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def canonical_json_sha256(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
    if not isinstance(contract, dict) or contract.get("algorithm") != SOURCE_HASH_ALGORITHM:
        raise ValueError("source_contract")
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


def verify_accepted_state(root: Path, command: Dict[str, Any]) -> Dict[str, Any]:
    path = relative_path(root, command.get("accepted_state_path"))
    algorithm = str(command.get("accepted_state_hash_algorithm") or "")
    expected = str(command.get("accepted_state_sha256") or "")
    if algorithm != ACCEPTED_HASH_ALGORITHM:
        raise ValueError("accepted_state_hash_algorithm")
    if not path.is_file():
        raise ValueError("accepted_state_missing")
    actual = canonical_json_sha256(path)
    if not expected or actual != expected:
        raise ValueError("accepted_state")
    return {"path": str(path), "algorithm": algorithm, "expected": expected, "actual": actual, "matched": True}


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


def track_count(timeline: Any, track_type: str) -> int:
    return as_int(safe_value(timeline, "GetTrackCount", track_type, default=0), 0)


def track_items(timeline: Any, track_type: str, track_index: int) -> List[Any]:
    value = safe_value(timeline, "GetItemListInTrack", track_type, track_index, default=[])
    return list(value or [])


def item_name(item: Any) -> str:
    return str(safe_value(item, "GetName", default="") or "")


def item_unique_id(item: Any) -> str:
    return str(safe_value(item, "GetUniqueId", default="") or "")


def item_start(item: Any) -> int:
    return as_int(safe_value(item, "GetStart", default=0), 0)


def item_end(item: Any) -> int:
    return as_int(safe_value(item, "GetEnd", default=0), 0)


def item_duration(item: Any) -> int:
    return as_int(safe_value(item, "GetDuration", default=item_end(item) - item_start(item)), 0)


def all_video_items(timeline: Any) -> List[Tuple[int, Any]]:
    rows: List[Tuple[int, Any]] = []
    for track_index in range(1, track_count(timeline, "video") + 1):
        for item in track_items(timeline, "video", track_index):
            rows.append((track_index, item))
    return rows


def caption_items(timeline: Any) -> List[Tuple[int, Any]]:
    return [(track, item) for track, item in all_video_items(timeline) if item_name(item).startswith(CAPTION_PREFIX)]


def item_track_index(timeline: Any, item: Any) -> Optional[int]:
    wanted_uid = item_unique_id(item)
    for track_index, candidate in all_video_items(timeline):
        if candidate is item:
            return track_index
        if wanted_uid and item_unique_id(candidate) == wanted_uid:
            return track_index
    return None


def item_summary(timeline: Any, item: Any) -> Dict[str, Any]:
    track_index = item_track_index(timeline, item)
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


def video_item_snapshot(timeline: Any) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for track_index, item in all_video_items(timeline):
        unique_id = item_unique_id(item)
        key = unique_id or f"object:{id(item)}"
        summary = item_summary(timeline, item)
        summary["track_index"] = track_index
        rows[key] = summary
    return rows


def find_new_video_items(
    timeline: Any,
    before: Dict[str, Dict[str, Any]],
) -> List[Any]:
    known = set(before)
    out: List[Any] = []
    for _track_index, item in all_video_items(timeline):
        key = item_unique_id(item) or f"object:{id(item)}"
        if key not in known:
            out.append(item)
    return out


def stabilize_native_title_context(
    resolve: Any,
    project: Any,
    timeline: Any,
    target_frame: int,
    target_track: int,
) -> Dict[str, Any]:
    page_before = str(safe_value(resolve, "GetCurrentPage", default="") or "")
    _value, open_page = direct_call(resolve, "OpenPage", "edit")
    time.sleep(0.25)
    page_after = str(safe_value(resolve, "GetCurrentPage", default="") or "")
    selected, select_call = direct_call(project, "SetCurrentTimeline", timeline)

    video_tracks = track_count(timeline, "video")
    audio_tracks = track_count(timeline, "audio")
    track_locks = []
    for index in range(1, video_tracks + 1):
        _result, row = direct_call(timeline, "SetTrackLock", "video", index, index != target_track)
        row["track_type"] = "video"
        row["track_index"] = index
        row["requested_locked"] = index != target_track
        track_locks.append(row)
    for index in range(1, audio_tracks + 1):
        _result, row = direct_call(timeline, "SetTrackLock", "audio", index, True)
        row["track_type"] = "audio"
        row["track_index"] = index
        row["requested_locked"] = True
        track_locks.append(row)

    playhead = set_playhead_to_frame(timeline, target_frame)
    target_lock = next(
        (
            row
            for row in track_locks
            if row.get("track_type") == "video" and row.get("track_index") == target_track
        ),
        None,
    )
    return {
        "page_before": page_before,
        "open_edit": open_page,
        "page_after": page_after,
        "select_timeline": select_call,
        "video_track_count": video_tracks,
        "audio_track_count": audio_tracks,
        "target_track": target_track,
        "track_locks": track_locks,
        "playhead": playhead,
        "ok": bool(
            page_after == "edit"
            and selected
            and video_tracks >= target_track
            and target_lock is not None
            and target_lock.get("ok") is True
            and playhead.get("ok")
        ),
    }


def source_timeline_snapshot(timeline: Any) -> Dict[str, Any]:
    rows = []
    for track_index, item in caption_items(timeline):
        rows.append({
            "name": item_name(item),
            "unique_id": item_unique_id(item),
            "track_index": track_index,
            "start": item_start(item),
            "end": item_end(item),
            "duration": item_duration(item),
            "fusion_comp_count": as_int(safe_value(item, "GetFusionCompCount", default=0), 0),
        })
    rows.sort(key=lambda row: (row["track_index"], row["start"], row["name"], row["unique_id"]))
    return {
        "name": timeline_name(timeline),
        "unique_id": timeline_unique_id(timeline),
        "caption_count": len(rows),
        "captions": rows,
    }


def delete_items(timeline: Any, items: Iterable[Any]) -> Dict[str, Any]:
    item_list = list(items)
    value, row = direct_call(timeline, "DeleteClips", item_list, False)
    return {"requested_count": len(item_list), "call": row, "ok": bool(value)}


def get_comp(item: Any) -> Any:
    count = as_int(safe_value(item, "GetFusionCompCount", default=0), 0)
    if count < 1:
        return None
    comp = safe_value(item, "GetFusionCompByIndex", 1, default=None)
    if comp is not None:
        return comp
    names = list(safe_value(item, "GetFusionCompNameList", default=[]) or [])
    if names:
        return safe_value(item, "GetFusionCompByName", names[0], default=None)
    return None


def get_text_tools(comp: Any) -> List[Any]:
    if comp is None:
        return []
    tools = safe_value(comp, "GetToolList", False, "TextPlus", default={}) or {}
    if isinstance(tools, dict) and tools:
        return list(tools.values())
    tools = safe_value(comp, "GetToolList", False, default={}) or {}
    found = []
    if isinstance(tools, dict):
        for tool in tools.values():
            attrs = safe_value(tool, "GetAttrs", default={}) or {}
            if str(attrs.get("TOOLS_RegID") or "") == "TextPlus":
                found.append(tool)
    return found


def find_input(tool: Any, input_name: str) -> Any:
    value = safe_value(tool, "FindInput", input_name, default=None)
    if value is not None:
        return value
    try:
        return getattr(tool, input_name)
    except BaseException:
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
    return bool(normalized is not None and all(abs(normalized[index] - expected[index]) <= tolerance for index in (0, 1)))


def read_text(tool: Any) -> str:
    value = read_input(tool, "StyledText", 0)
    return value if isinstance(value, str) else str(value or "")


def set_static_input(tool: Any, input_name: str, value: Any) -> Dict[str, Any]:
    attempts = []
    method = getattr(tool, "SetInput", None)
    if callable(method):
        try:
            returned = method(input_name, value)
            attempts.append({"method": "SetInput(name, value)", "returned": json_safe(returned), "error": None})
        except BaseException as exc:
            attempts.append({"method": "SetInput(name, value)", "returned": None, "error": compact_exception(exc)})
        actual = read_input(tool, input_name, 0)
        if actual == value:
            return {"input": input_name, "expected": json_safe(value), "actual": json_safe(actual), "matched": True, "attempts": attempts, "ok": True}
    try:
        setattr(tool, input_name, value)
        attempts.append({"method": f"setattr({input_name}, value)", "returned": True, "error": None})
    except BaseException as exc:
        attempts.append({"method": f"setattr({input_name}, value)", "returned": None, "error": compact_exception(exc)})
    actual = read_input(tool, input_name, 0)
    matched = actual == value
    return {"input": input_name, "expected": json_safe(value), "actual": json_safe(actual), "matched": matched, "attempts": attempts, "ok": matched}


def set_keyframe(tool: Any, input_name: str, frame: int, value: Any) -> Dict[str, Any]:
    attempts = []
    input_object = find_input(tool, input_name)
    if input_object is not None:
        try:
            input_object[int(frame)] = value
            attempts.append({"method": "FindInput(name)[frame] = value", "returned": True, "error": None})
        except BaseException as exc:
            attempts.append({"method": "FindInput(name)[frame] = value", "returned": None, "error": compact_exception(exc)})
        actual = read_input(tool, input_name, int(frame))
        if point_matches(actual, value):
            return {
                "input": input_name,
                "frame": int(frame),
                "expected": value,
                "actual": json_safe(actual),
                "matched": True,
                "attempts": attempts,
                "ok": True,
            }
    method = getattr(tool, "SetInput", None)
    if callable(method):
        try:
            returned = method(input_name, value, int(frame))
            attempts.append({"method": "SetInput(name, value, frame)", "returned": json_safe(returned), "error": None})
        except BaseException as exc:
            attempts.append({"method": "SetInput(name, value, frame)", "returned": None, "error": compact_exception(exc)})
    actual = read_input(tool, input_name, int(frame))
    matched = point_matches(actual, value)
    return {
        "input": input_name,
        "frame": int(frame),
        "expected": value,
        "actual": json_safe(actual),
        "matched": matched,
        "attempts": attempts,
        "ok": matched,
    }


def set_item_name(item: Any, name: str) -> Dict[str, Any]:
    value, row = direct_call(item, "SetName", name)
    actual = item_name(item)
    return {"call": row, "actual": actual, "ok": bool(value and actual == name)}


def parse_timecode(value: str) -> Tuple[int, int, int, int, str]:
    text = str(value or "").strip()
    delimiter = ";" if ";" in text else ":"
    parts = re_split_timecode(text)
    if len(parts) != 4:
        raise ValueError(f"timecode:{text}")
    return int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]), delimiter


def re_split_timecode(value: str) -> List[str]:
    return value.replace(";", ":").split(":")


def add_timecode_frames(value: str, frames: int, fps: int) -> str:
    if fps <= 0:
        raise ValueError("fps")
    hours, minutes, seconds, frame, delimiter = parse_timecode(value)
    total = (((hours * 60) + minutes) * 60 + seconds) * fps + frame + int(frames)
    if total < 0:
        raise ValueError("negative_timecode")
    out_frame = total % fps
    total //= fps
    out_seconds = total % 60
    total //= 60
    out_minutes = total % 60
    out_hours = total // 60
    return f"{out_hours:02d}:{out_minutes:02d}:{out_seconds:02d}{delimiter}{out_frame:02d}"


def set_playhead_to_frame(timeline: Any, target_frame: int) -> Dict[str, Any]:
    fps_value = safe_value(timeline, "GetSetting", "timelineFrameRate", default="")
    fps = int(round(as_float(fps_value, 0.0)))
    start_frame = as_int(safe_value(timeline, "GetStartFrame", default=0), 0)
    start_timecode = str(safe_value(timeline, "GetStartTimecode", default="") or "")
    if fps != EXPECTED_FPS:
        return {"ok": False, "error": f"fps:{fps_value}", "fps": fps_value}
    if target_frame < start_frame:
        return {"ok": False, "error": f"target_before_start:{target_frame}:{start_frame}"}
    requested_timecode = add_timecode_frames(start_timecode, target_frame - start_frame, fps)
    value, call = direct_call(timeline, "SetCurrentTimecode", requested_timecode)
    actual_timecode = str(safe_value(timeline, "GetCurrentTimecode", default="") or "")
    return {
        "fps": fps,
        "timeline_start_frame": start_frame,
        "timeline_start_timecode": start_timecode,
        "target_frame": target_frame,
        "requested_timecode": requested_timecode,
        "actual_timecode": actual_timecode,
        "call": call,
        "ok": bool(value and actual_timecode == requested_timecode),
    }


def find_item_by_unique_id(timeline: Any, unique_id: str) -> Tuple[Optional[int], Any]:
    matches = [(track, item) for track, item in all_video_items(timeline) if item_unique_id(item) == unique_id]
    if len(matches) != 1:
        return None, None
    return matches[0]


def save_project(project_manager: Any) -> Dict[str, Any]:
    value, row = direct_call(project_manager, "SaveProject")
    return {"call": row, "success": bool(value)}


def cleanup_probe(
    resolve: Any,
    probe_name: str,
    original_name: str,
    root: Path,
    accepted_hash: str,
    original_page: str = "",
) -> Dict[str, Any]:
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
        else:
            cleanup["errors"].append("original_missing")
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
        current = safe_value(project, "GetCurrentTimeline", default=None)
        cleanup["original_restored"] = bool(current is not None and timeline_name(current) == original_name)
        if original_page:
            _value, page_restore = direct_call(resolve, "OpenPage", original_page)
            cleanup["restore_page"] = page_restore
            cleanup["original_page_restored"] = (
                str(safe_value(resolve, "GetCurrentPage", default="") or "") == original_page
            )
        else:
            cleanup["original_page_restored"] = True
    except BaseException as exc:
        cleanup["errors"].append(compact_exception(exc))
        cleanup["traceback"] = traceback.format_exc()
    accepted_path = root / ACCEPTED_STATE_RELATIVE_PATH
    cleanup["accepted_state_unchanged"] = bool(
        accepted_path.is_file() and canonical_json_sha256(accepted_path) == accepted_hash
    )
    cleanup["finished_at"] = utc_now()
    cleanup["ok"] = bool(
        not cleanup["errors"]
        and cleanup.get("probe_deleted") is True
        and cleanup.get("original_restored") is True
        and cleanup.get("original_page_restored") is True
        and cleanup.get("accepted_state_unchanged") is True
    )
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
    probe = command.get("probe")
    if not isinstance(probe, dict):
        raise ValueError("probe")
    probe_name = str(probe.get("timeline_name") or "")
    if not probe_name:
        raise ValueError("probe_timeline_name")
    accepted_hash = str(command.get("accepted_state_sha256") or "")

    report: Dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "ok": False,
        "architecture_viable": False,
        "started_at": utc_now(),
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "probe_timeline_name": probe_name,
        "failures": [],
        "save_call_count": 0,
        "visual_review_required": False,
        "probe_timeline_deleted": False,
    }
    original_name = ""
    original_page = ""
    duplicate_created = False
    source_before: Optional[Dict[str, Any]] = None

    try:
        source_contract = verify_source_contract(root, command)
        accepted_contract = verify_accepted_state(root, command)
        report["source_contract_verified_count"] = source_contract["verified_count"]
        write_json(report_dir / "source_contract_verification.json", {
            "source_contract": source_contract,
            "accepted_state": accepted_contract,
        })

        project_manager, project, media_pool, resolve_calls = get_project(resolve)
        original_page = str(safe_value(resolve, "GetCurrentPage", default="") or "")
        current = safe_value(project, "GetCurrentTimeline", default=None)
        original_name = timeline_name(current) if current is not None else ""
        if not original_name:
            raise RuntimeError("original_timeline")
        source = find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        source_before = source_timeline_snapshot(source)
        if source_before["caption_count"] != EXPECTED_SOURCE_CAPTION_COUNT:
            raise RuntimeError(f"source_caption_count:{source_before['caption_count']}")

        preflight = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "checked_at": utc_now(),
            "resolve_calls": resolve_calls,
            "original_timeline_name": original_name,
            "source_timeline": source_before,
            "probe": {
                "timeline_name": probe_name,
                "target_frame": TARGET_FRAME,
                "target_track": TARGET_TRACK,
                "required_page": "edit",
                "title_name": TITLE_NAME,
                "probe_text": PROBE_TEXT,
                "center_keyframes": CENTER_KEYFRAMES,
            },
        }
        write_json(report_dir / "probe_preflight.json", preflight)

        value, duplicate_call = direct_call(source, "DuplicateTimeline", probe_name)
        duplicate = value if value is not None else find_timeline(project, probe_name)
        if duplicate is None:
            raise RuntimeError("duplicate_timeline")
        duplicate_created = True
        value, set_current_call = direct_call(project, "SetCurrentTimeline", duplicate)
        if not value:
            raise RuntimeError("select_duplicate")

        captions_before = caption_items(duplicate)
        deletion = delete_items(duplicate, [item for _, item in captions_before])
        time.sleep(0.20)
        captions_after = caption_items(duplicate)
        if not deletion.get("ok") or captions_after:
            raise RuntimeError(f"caption_cleanup:{len(captions_after)}")

        insertion_context = stabilize_native_title_context(
            resolve,
            project,
            duplicate,
            TARGET_FRAME,
            TARGET_TRACK,
        )
        if not insertion_context.get("ok"):
            write_json(report_dir / "duplicate_timeline_setup.json", {
                "duplicate_call": duplicate_call,
                "set_current_call": set_current_call,
                "duplicate_name": timeline_name(duplicate),
                "duplicate_unique_id": timeline_unique_id(duplicate),
                "caption_count_before_delete": len(captions_before),
                "caption_delete": deletion,
                "caption_count_after_delete": len(captions_after),
                "insertion_context": insertion_context,
            })
            raise RuntimeError("native_title_context")

        setup = {
            "duplicate_call": duplicate_call,
            "set_current_call": set_current_call,
            "duplicate_name": timeline_name(duplicate),
            "duplicate_unique_id": timeline_unique_id(duplicate),
            "caption_count_before_delete": len(captions_before),
            "caption_delete": deletion,
            "caption_count_after_delete": len(captions_after),
            "insertion_context": insertion_context,
        }
        write_json(report_dir / "duplicate_timeline_setup.json", setup)

        before_items = video_item_snapshot(duplicate)
        returned_item, insert_call = direct_call(
            duplicate,
            "InsertFusionTitleIntoTimeline",
            TITLE_NAME,
        )
        time.sleep(0.50)
        new_items = find_new_video_items(duplicate, before_items)
        inserted = returned_item
        detected_by = "return_value" if returned_item is not None else None
        if inserted is None and len(new_items) == 1:
            inserted = new_items[0]
            detected_by = "timeline_delta"

        new_item_summaries = [item_summary(duplicate, item) for item in new_items]
        if inserted is None:
            write_json(report_dir / "native_title_insertion.json", {
                "call": insert_call,
                "returned_item": None,
                "new_items": new_item_summaries,
                "new_item_count": len(new_items),
                "detected_by": detected_by,
                "ok": False,
            })
            raise RuntimeError(f"native_title_insert:new_items:{len(new_items)}")

        name_result = set_item_name(inserted, PROBE_ITEM_NAME)
        immediate_summary = item_summary(duplicate, inserted)
        insertion = {
            "call": insert_call,
            "detected_by": detected_by,
            "new_items": new_item_summaries,
            "new_item_count": len(new_items),
            "name_result": name_result,
            "returned_item": item_summary(duplicate, returned_item) if returned_item is not None else None,
            "detected_item": immediate_summary,
            "placement_ok": immediate_summary["start"] == TARGET_FRAME,
            "track_ok": immediate_summary["track_index"] == TARGET_TRACK,
            "unique_id_ok": bool(immediate_summary["unique_id"]),
            "fusion_comp_count_ok": immediate_summary["fusion_comp_count"] >= 1,
        }
        insertion["ok"] = bool(
            insertion["placement_ok"]
            and insertion["track_ok"]
            and insertion["unique_id_ok"]
            and insertion["fusion_comp_count_ok"]
        )
        write_json(report_dir / "native_title_insertion.json", insertion)
        if not insertion["ok"]:
            raise RuntimeError("native_title_contract")

        comp = get_comp(inserted)
        text_tools = get_text_tools(comp)
        if comp is None or len(text_tools) != 1:
            raise RuntimeError(f"native_textplus_tool_count:{len(text_tools)}")
        text_tool = text_tools[0]

        text_write = set_static_input(text_tool, "StyledText", PROBE_TEXT)
        center_writes = [set_keyframe(text_tool, "Center", frame, value) for frame, value in CENTER_KEYFRAMES]
        immediate_readback = {
            "text": read_text(text_tool),
            "center_keyframes": [
                {
                    "frame": frame,
                    "expected": value,
                    "actual": json_safe(read_input(text_tool, "Center", frame)),
                    "matched": point_matches(read_input(text_tool, "Center", frame), value),
                }
                for frame, value in CENTER_KEYFRAMES
            ],
        }
        mutation = {
            "text_tool_count": len(text_tools),
            "text_write": text_write,
            "center_writes": center_writes,
            "immediate_readback": immediate_readback,
        }
        mutation["ok"] = bool(
            text_write["ok"]
            and all(row["ok"] for row in center_writes)
            and immediate_readback["text"] == PROBE_TEXT
            and all(row["matched"] for row in immediate_readback["center_keyframes"])
        )
        write_json(report_dir / "native_textplus_mutation.json", mutation)
        if not mutation["ok"]:
            raise RuntimeError("native_textplus_mutation")

        first_save = save_project(project_manager)
        if first_save["success"]:
            report["save_call_count"] += 1
        if not first_save["success"]:
            raise RuntimeError("save_probe")

        project_manager, project, media_pool, reacquire_calls = get_project(resolve)
        duplicate_after = find_timeline(project, probe_name)
        source_after = find_timeline(project, SOURCE_TIMELINE_NAME)
        if duplicate_after is None or source_after is None:
            raise RuntimeError("persistent_timeline_reacquire")
        track_after, item_after = find_item_by_unique_id(duplicate_after, immediate_summary["unique_id"])
        if item_after is None:
            raise RuntimeError("persistent_item_reacquire")
        comp_after = get_comp(item_after)
        tools_after = get_text_tools(comp_after)
        if len(tools_after) != 1:
            raise RuntimeError(f"persistent_textplus_tool_count:{len(tools_after)}")
        tool_after = tools_after[0]
        persistent_summary = item_summary(duplicate_after, item_after)
        persistent_centers = [
            {
                "frame": frame,
                "expected": value,
                "actual": json_safe(read_input(tool_after, "Center", frame)),
                "matched": point_matches(read_input(tool_after, "Center", frame), value),
            }
            for frame, value in CENTER_KEYFRAMES
        ]
        source_after_snapshot = source_timeline_snapshot(source_after)
        accepted_unchanged = bool(
            (root / ACCEPTED_STATE_RELATIVE_PATH).is_file()
            and canonical_json_sha256(root / ACCEPTED_STATE_RELATIVE_PATH) == accepted_hash
        )
        persistent = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "checked_at": utc_now(),
            "reacquire_calls": reacquire_calls,
            "item": persistent_summary,
            "track_reacquired": track_after,
            "text_tool_count": len(tools_after),
            "text_actual": read_text(tool_after),
            "text_matched": read_text(tool_after) == PROBE_TEXT,
            "center_keyframes": persistent_centers,
            "center_keyframes_matched": all(row["matched"] for row in persistent_centers),
            "placement_matched": persistent_summary["start"] == TARGET_FRAME,
            "source_timeline_unchanged": source_after_snapshot == source_before,
            "accepted_state_unchanged": accepted_unchanged,
            "save": first_save,
        }
        persistent["ok"] = bool(
            persistent["text_matched"]
            and persistent["center_keyframes_matched"]
            and persistent["placement_matched"]
            and persistent["source_timeline_unchanged"]
            and persistent["accepted_state_unchanged"]
            and persistent_summary["fusion_comp_count"] >= 1
        )
        write_json(report_dir / "persistent_readback.json", persistent)
        if not persistent["ok"]:
            raise RuntimeError("persistent_readback")

        cleanup = cleanup_probe(resolve, probe_name, original_name, root, accepted_hash, original_page)
        if cleanup.get("save_cleanup", {}).get("success"):
            report["save_call_count"] += 1
        write_json(report_dir / "probe_cleanup.json", cleanup)
        if not cleanup.get("ok"):
            raise RuntimeError("probe_cleanup")

        report.update({
            "ok": True,
            "architecture_viable": True,
            "finished_at": utc_now(),
            "native_title_inserted": True,
            "inserted_item": persistent_summary,
            "fusion_comp_count": persistent_summary["fusion_comp_count"],
            "textplus_tool_count": len(tools_after),
            "text_readback": persistent["text_actual"],
            "center_readback_count": sum(1 for row in persistent_centers if row["matched"]),
            "persistent_readback_ok": True,
            "source_timeline_unchanged": True,
            "accepted_state_unchanged": True,
            "probe_timeline_deleted": True,
            "original_timeline_restored": True,
            "original_page_restored": cleanup.get("original_page_restored"),
            "insertion_detected_by": insertion.get("detected_by"),
            "visual_review_required": False,
            "cleanup": cleanup,
        })
        write_json(report_dir / "probe_result.json", report)
        return report

    except BaseException as exc:
        report["failures"].append(compact_exception(exc))
        report["traceback"] = traceback.format_exc()
        cleanup = cleanup_probe(resolve, probe_name, original_name or SOURCE_TIMELINE_NAME, root, accepted_hash, original_page) if duplicate_created else {
            "attempted": False,
            "probe_deleted": True,
            "original_restored": True,
            "accepted_state_unchanged": bool(
                (root / ACCEPTED_STATE_RELATIVE_PATH).is_file()
                and canonical_json_sha256(root / ACCEPTED_STATE_RELATIVE_PATH) == accepted_hash
            ),
            "ok": True,
        }
        if cleanup.get("save_cleanup", {}).get("success"):
            report["save_call_count"] += 1
        report.update({
            "ok": False,
            "architecture_viable": False,
            "finished_at": utc_now(),
            "cleanup": cleanup,
            "probe_timeline_deleted": cleanup.get("probe_deleted"),
            "original_timeline_restored": cleanup.get("original_restored"),
            "original_page_restored": cleanup.get("original_page_restored"),
            "accepted_state_unchanged": cleanup.get("accepted_state_unchanged"),
        })
        write_json(report_dir / "probe_cleanup.json", cleanup)
        write_json(report_dir / "probe_result.json", report)
        return report
