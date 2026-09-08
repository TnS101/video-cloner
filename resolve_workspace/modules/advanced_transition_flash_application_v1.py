"""Apply source-backed flash transitions to one isolated Resolve timeline.

Architecture family: advanced_transition_flash_application_v1.

The accepted timeline is duplicated once. Five high-confidence ``flash_cut`` events
are represented by short, full-frame white Fusion Background carriers on one new
top video track. Existing clips/captions/occlusion items are never edited.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

TASK_ID = "DZSQH7AUHJT_ADVANCED_TRANSITION_FLASH_APPLICATION_V1"
MODE = "ADVANCED_TRANSITION_FLASH_APPLICATION_V1"
VERSION = "advanced_transition_flash_application_v1_1"

SOURCE_TIMELINE_NAME = (
    "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_"
    "confirmed74_repair_metrics_v1_occlusion_complete_v4"
)
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_flash_transition_v1"
EXPECTED_TEXTPLUS_COUNT = 114
CAPTION_PREFIXES = ("VC_TEXTPLUS_", "VC_VISUAL_FIRST_FULL_")
EXPECTED_FLASH_FRAMES = (96, 377, 426, 454, 758)
FLASH_PREFIX = "VC_FLASH_"
FLASH_TOOL_PREFIX = "VC_FLASH_BG_"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def normalized_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    try:
        return float(value)
    except Exception:
        return str(value)


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(json_safe(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def relative_path(root: Path, value: Any) -> Path:
    text = str(value or "")
    if not text:
        raise ValueError("relative_path")
    candidate = Path(text)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"path_outside_repository:{text}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path_outside_repository:{text}") from exc
    return resolved


def verify_source_contract(root: Path, command: Mapping[str, Any]) -> Dict[str, Any]:
    contract = command.get("source_contract")
    if not isinstance(contract, Mapping) or contract.get("algorithm") != "sha256_text_lf_normalized":
        raise ValueError("source_contract")
    hashes = contract.get("hashes")
    if not isinstance(hashes, Mapping) or not hashes:
        raise ValueError("source_contract_hashes")
    rows = []
    for relative, expected in hashes.items():
        path = relative_path(root, relative)
        actual = normalized_sha256(path) if path.is_file() else ""
        matched = actual == str(expected)
        rows.append({"path": str(relative), "expected": expected, "actual": actual, "matched": matched})
        if not matched:
            raise ValueError(f"source_hash:{relative}")
    return {"algorithm": contract["algorithm"], "verified_count": len(rows), "rows": rows, "ok": True}


def validate_plan(plan: Mapping[str, Any]) -> None:
    if plan.get("schema") != "video_cloner_flash_transition_plan" or plan.get("schema_version") != 1:
        raise ValueError("plan_schema")
    if plan.get("task_id") != TASK_ID:
        raise ValueError("plan_task_id")
    if plan.get("source_timeline_name") != SOURCE_TIMELINE_NAME:
        raise ValueError("plan_source_timeline")
    if plan.get("target_timeline_name") != TARGET_TIMELINE_NAME:
        raise ValueError("plan_target_timeline")
    if int(plan.get("expected_textplus_count") or 0) != EXPECTED_TEXTPLUS_COUNT:
        raise ValueError("plan_textplus_count")
    rows = plan.get("flashes")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED_FLASH_FRAMES):
        raise ValueError("plan_flash_count")
    actual_frames = tuple(int(row.get("cut_frame") or -1) for row in rows if isinstance(row, Mapping))
    if actual_frames != EXPECTED_FLASH_FRAMES:
        raise ValueError(f"plan_flash_frames:{actual_frames}")
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise ValueError(f"plan_flash_row:{index}")
        cut = EXPECTED_FLASH_FRAMES[index - 1]
        expected_name = f"{FLASH_PREFIX}{index:03d}_frame_{cut:04d}"
        checks = (
            row.get("transition_type") == "flash_cut",
            row.get("confidence") == "high",
            row.get("editor_actionable") is True,
            int(row.get("duration_frames") or 0) == 4,
            int(row.get("outgoing_frames") or 0) == 2,
            int(row.get("incoming_frames") or 0) == 2,
            int(row.get("start_frame") or -1) == cut - 2,
            row.get("name") == expected_name,
            row.get("flash_color") == [1.0, 1.0, 1.0],
            row.get("alpha_keyframes") == [[0, 0.0], [2, 0.75], [3, 0.0]],
        )
        if not all(checks):
            raise ValueError(f"plan_flash_contract:{index}")
    plan_for_hash = dict(plan)
    expected_hash = str(plan_for_hash.pop("plan_sha256", "") or "")
    if not expected_hash or canonical_sha256(plan_for_hash) != expected_hash:
        raise ValueError("plan_hash")


def safe_call(obj: Any, method: str, *args: Any, default: Any = None) -> Any:
    try:
        fn = getattr(obj, method, None)
        return fn(*args) if callable(fn) else default
    except Exception:
        return default


def direct_call(obj: Any, method: str, *args: Any) -> Tuple[Any, Dict[str, Any]]:
    row: Dict[str, Any] = {"method": method, "args": [json_safe(arg) for arg in args], "ok": False}
    try:
        fn = getattr(obj, method, None)
        if not callable(fn):
            row["error"] = "method_missing"
            return None, row
        value = fn(*args)
        row["ok"] = value is not False and value is not None
        row["returned"] = json_safe(value)
        return value, row
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
        return None, row


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def timeline_name(timeline: Any) -> str:
    return str(safe_call(timeline, "GetName", default="") or "")


def timeline_count(project: Any) -> int:
    return as_int(safe_call(project, "GetTimelineCount", default=0), 0)


def find_timeline(project: Any, name: str) -> Any:
    for index in range(1, timeline_count(project) + 1):
        timeline = safe_call(project, "GetTimelineByIndex", index, default=None)
        if timeline is not None and timeline_name(timeline) == name:
            return timeline
    return None


def track_count(timeline: Any, kind: str = "video") -> int:
    return as_int(safe_call(timeline, "GetTrackCount", kind, default=0), 0)


def track_items(timeline: Any, kind: str, index: int) -> List[Any]:
    value = safe_call(timeline, "GetItemListInTrack", kind, index, default=[]) or []
    return list(value) if isinstance(value, (list, tuple)) else []


def all_video_items(timeline: Any) -> List[Tuple[int, Any]]:
    return [
        (index, item)
        for index in range(1, track_count(timeline, "video") + 1)
        for item in track_items(timeline, "video", index)
    ]


def item_name(item: Any) -> str:
    return str(safe_call(item, "GetName", default="") or "")


def item_start(item: Any) -> int:
    return as_int(safe_call(item, "GetStart", default=0), 0)


def item_end(item: Any) -> int:
    return as_int(safe_call(item, "GetEnd", default=0), 0)


def item_duration(item: Any) -> int:
    return as_int(safe_call(item, "GetDuration", default=item_end(item) - item_start(item)), 0)


def item_uid(item: Any) -> str:
    return str(safe_call(item, "GetUniqueId", default="") or "")


def caption_snapshot(timeline: Any) -> Dict[str, Any]:
    rows = []
    for track_index, item in all_video_items(timeline):
        name = item_name(item)
        if not name.startswith(CAPTION_PREFIXES):
            continue
        rows.append({
            "name": name,
            "track_index": track_index,
            "start": item_start(item),
            "end": item_end(item),
            "duration": item_duration(item),
        })
    rows.sort(key=lambda row: (row["name"], row["track_index"], row["start"], row["end"]))
    return {
        "count": len(rows),
        "rows": rows,
        "sha256": canonical_sha256(rows),
        "video_track_count": track_count(timeline, "video"),
    }


def choose_carrier_source(timeline: Any, minimum_duration: int) -> Dict[str, Any]:
    attempts = []
    for item in track_items(timeline, "video", 1):
        media_pool_item = safe_call(item, "GetMediaPoolItem", default=None)
        if media_pool_item is None:
            continue
        duration = item_duration(item)
        left_offset = max(0, as_int(safe_call(item, "GetLeftOffset", default=0), 0))
        attempts.append({
            "name": item_name(item),
            "duration": duration,
            "left_offset": left_offset,
            "media_pool_item_name": str(safe_call(media_pool_item, "GetName", default="") or ""),
        })
        if duration >= minimum_duration:
            return {
                "ok": True,
                "item": item,
                "media_pool_item": media_pool_item,
                "source_start": left_offset,
                "attempts": attempts,
            }
    return {"ok": False, "attempts": attempts, "error": f"carrier_source:{minimum_duration}"}


def ensure_extra_video_track(timeline: Any, source_track_count: int) -> Dict[str, Any]:
    before = track_count(timeline, "video")
    if before != source_track_count:
        return {"ok": False, "before": before, "error": "duplicate_track_count_changed"}
    value, call = direct_call(timeline, "AddTrack", "video")
    after = track_count(timeline, "video")
    return {
        "ok": bool(value and after == source_track_count + 1),
        "before": before,
        "after": after,
        "target_track": after,
        "call": call,
    }


def set_item_name(item: Any, name: str) -> Dict[str, Any]:
    attempts = []
    for method in ("SetName", "SetClipName"):
        value, row = direct_call(item, method, name)
        attempts.append(row)
        if value and item_name(item) == name:
            return {"ok": True, "readback": item_name(item), "attempts": attempts}
    value, row = direct_call(item, "SetProperty", "Name", name)
    attempts.append(row)
    return {"ok": bool(value and item_name(item) == name), "readback": item_name(item), "attempts": attempts}


def item_track_index(timeline: Any, item: Any) -> Optional[int]:
    wanted_uid = item_uid(item)
    for index, candidate in all_video_items(timeline):
        if wanted_uid and item_uid(candidate) == wanted_uid:
            return index
        if candidate is item:
            return index
    return None


def append_flash_carriers(
    media_pool: Any,
    timeline: Any,
    carrier: Mapping[str, Any],
    flashes: Sequence[Mapping[str, Any]],
    target_track: int,
) -> Dict[str, Any]:
    before_uids = {item_uid(item) for _, item in all_video_items(timeline) if item_uid(item)}
    clip_infos = []
    for row in flashes:
        duration = int(row["duration_frames"])
        source_start = int(carrier["source_start"])
        # Resolve 21 treats clipInfo.endFrame as an exclusive source endpoint
        # on the proven media-backed AppendToTimeline path.  Passing
        # ``source_start + duration - 1`` creates a timeline item one frame
        # short.  Use the half-open source range [start, start + duration).
        clip_infos.append({
            "mediaPoolItem": carrier["media_pool_item"],
            "startFrame": source_start,
            "endFrame": source_start + duration,
            "mediaType": 1,
            "trackIndex": target_track,
            "recordFrame": int(row["start_frame"]),
        })
    returned, call = direct_call(media_pool, "AppendToTimeline", clip_infos)
    returned_items = list(returned) if isinstance(returned, (list, tuple)) else []
    detected = [
        item for _, item in all_video_items(timeline)
        if item_uid(item) and item_uid(item) not in before_uids
    ]
    # Resolve can return proxy TimelineItem handles from AppendToTimeline that are
    # not identity-equivalent to the handles returned by GetItemListInTrack.
    # Prefer the post-append timeline scan whenever it found the full inserted set;
    # those objects have proven track membership and can be validated by exact
    # track/start/duration before naming or Fusion mutation.
    if len(detected) == len(flashes):
        candidates = detected
        candidate_source = "detected_timeline_items"
    elif len(returned_items) == len(flashes):
        candidates = returned_items
        candidate_source = "append_return_items"
    else:
        candidates = detected if detected else returned_items
        candidate_source = "partial_detected" if detected else "partial_returned"
    remaining = list(candidates)
    candidate_rows = [
        {
            "uid": item_uid(item),
            "track_index": item_track_index(timeline, item),
            "start": item_start(item),
            "end": item_end(item),
            "duration": item_duration(item),
            "name": item_name(item),
        }
        for item in candidates
    ]
    assigned = []
    rows = []
    for spec in flashes:
        match_index = None
        for index, item in enumerate(remaining):
            if (
                item_track_index(timeline, item) == target_track
                and item_start(item) == int(spec["start_frame"])
                and item_duration(item) == int(spec["duration_frames"])
            ):
                match_index = index
                break
        if match_index is None:
            rows.append({"name": spec["name"], "ok": False, "error": "inserted_item_not_found"})
            continue
        item = remaining.pop(match_index)
        rename = set_item_name(item, str(spec["name"]))
        rows.append({
            "name": spec["name"],
            "track_index": item_track_index(timeline, item),
            "start": item_start(item),
            "end": item_end(item),
            "duration": item_duration(item),
            "rename": rename,
            "ok": rename.get("ok") is True,
        })
        assigned.append((spec, item))
    return {
        "ok": len(assigned) == len(flashes) and all(row.get("ok") for row in rows),
        "call": call,
        "requested_count": len(flashes),
        "source_api_end_semantics": "exclusive",
        "requested_source_ranges": [
            {
                "name": str(spec["name"]),
                "source_start": int(info["startFrame"]),
                "source_end_frame_api": int(info["endFrame"]),
                "requested_duration": int(spec["duration_frames"]),
                "record_frame": int(info["recordFrame"]),
            }
            for spec, info in zip(flashes, clip_infos)
        ],
        "returned_count": len(returned_items),
        "detected_count": len(detected),
        "candidate_source": candidate_source,
        "candidate_count": len(candidates),
        "candidate_rows": candidate_rows,
        "assigned_count": len(assigned),
        "rows": rows,
        "assigned": assigned,
    }


def fusion_tools(comp: Any) -> List[Any]:
    value = safe_call(comp, "GetToolList", False, default={}) or {}
    return list(value.values()) if isinstance(value, dict) else list(value or [])


def fusion_tool_regid(tool: Any) -> str:
    attrs = safe_call(tool, "GetAttrs", default={}) or {}
    return str(attrs.get("TOOLS_RegID") or "")


def fusion_tool_name(tool: Any) -> str:
    attrs = safe_call(tool, "GetAttrs", default={}) or {}
    return str(attrs.get("TOOLS_Name") or attrs.get("TOOLS_NameDisp") or "")


def find_tool(comp: Any, regid: str) -> Any:
    wanted = regid.lower()
    for tool in fusion_tools(comp):
        if fusion_tool_regid(tool).lower() == wanted:
            return tool
    return None


def find_named_tool(comp: Any, name: str) -> Any:
    wanted = name.lower()
    for tool in fusion_tools(comp):
        if fusion_tool_name(tool).lower() == wanted:
            return tool
    return None


def set_tool_name(tool: Any, name: str) -> bool:
    try:
        tool.SetAttrs({"TOOLS_Name": name})
        return fusion_tool_name(tool) == name
    except Exception:
        try:
            setattr(tool, "Name", name)
            return True
        except Exception:
            return False


def get_or_create_comp(item: Any) -> Tuple[Any, Dict[str, Any]]:
    count = as_int(safe_call(item, "GetFusionCompCount", default=0), 0)
    if count > 0:
        comp = safe_call(item, "GetFusionCompByIndex", 1, default=None)
        if comp is not None:
            return comp, {"ok": True, "created": False, "existing_count": count}
    value, call = direct_call(item, "AddFusionComp")
    comp = value
    if comp is None:
        comp = safe_call(item, "GetFusionCompByIndex", 1, default=None)
    return comp, {
        "ok": comp is not None,
        "created": comp is not None,
        "existing_count": count,
        "call": call,
        "after_count": as_int(safe_call(item, "GetFusionCompCount", default=0), 0),
    }


def find_input_object(tool: Any, name: str) -> Any:
    value = safe_call(tool, "FindInput", name, default=None)
    if value is not None:
        return value
    try:
        return getattr(tool, name)
    except Exception:
        return None


def connected_output(input_object: Any) -> Any:
    if input_object is None:
        return None
    return safe_call(input_object, "GetConnectedOutput", default=None)


def ensure_bezier_modifier(comp: Any, tool: Any, name: str) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    input_object = find_input_object(tool, name)
    if input_object is None:
        return {"ok": False, "created": False, "input": name, "attempts": attempts, "error": "input_missing"}
    if connected_output(input_object) is not None:
        return {"ok": True, "created": False, "input": name, "modifier": "existing", "attempts": attempts}

    value, call = direct_call(tool, "AddModifier", name, "BezierSpline")
    attempts.append({"method": "Tool.AddModifier", "call": call, "returned": json_safe(value)})
    input_object = find_input_object(tool, name)
    if connected_output(input_object) is not None:
        return {"ok": True, "created": True, "input": name, "modifier": "BezierSpline", "attempts": attempts}

    try:
        factory = getattr(comp, "BezierSpline")
        modifier = factory()
        setattr(tool, name, modifier)
        attempts.append({"method": "comp.BezierSpline()", "assigned": True})
    except Exception as exc:
        attempts.append({"method": "comp.BezierSpline()", "assigned": False, "error": f"{type(exc).__name__}: {exc}"})

    input_object = find_input_object(tool, name)
    connected = connected_output(input_object) is not None
    return {
        "ok": connected,
        "created": connected,
        "input": name,
        "modifier": "BezierSpline",
        "attempts": attempts,
        "error": None if connected else "modifier_not_connected",
    }


def write_animated_scalar(tool: Any, name: str, frame: int, value: float) -> Dict[str, Any]:
    expected = float(value)
    frame = int(frame)
    attempts: List[Dict[str, Any]] = []

    input_object = find_input_object(tool, name)
    if input_object is not None:
        try:
            input_object[frame] = expected
            readback = read_input(tool, name, frame)
            matched = bool(readback.get("ok") and numeric_close(readback.get("value"), expected))
            attempts.append({
                "method": "Input[frame]",
                "frame": frame,
                "value": expected,
                "readback": readback,
                "matched": matched,
            })
            if matched:
                return {"ok": True, "attempts": attempts, "readback": readback}
        except Exception as exc:
            attempts.append({"method": "Input[frame]", "frame": frame, "error": f"{type(exc).__name__}: {exc}"})

    fn = getattr(tool, "SetInput", None)
    if callable(fn):
        try:
            returned = fn(name, expected, frame)
            readback = read_input(tool, name, frame)
            matched = bool(readback.get("ok") and numeric_close(readback.get("value"), expected))
            attempts.append({
                "method": "SetInput(name,value,frame)",
                "frame": frame,
                "value": expected,
                "returned": json_safe(returned),
                "readback": readback,
                "matched": matched,
            })
            if matched:
                return {"ok": True, "attempts": attempts, "readback": readback}
        except Exception as exc:
            attempts.append({"method": "SetInput(name,value,frame)", "frame": frame, "error": f"{type(exc).__name__}: {exc}"})

    return {"ok": False, "attempts": attempts}


def set_input(tool: Any, name: str, value: Any, frame: Optional[int] = None) -> Dict[str, Any]:
    attempts = []
    fn = getattr(tool, "SetInput", None)
    if callable(fn):
        try:
            result = fn(name, value) if frame is None else fn(name, value, int(frame))
            attempts.append({"method": "SetInput", "frame": frame, "ok": bool(result), "value": value})
            if result:
                return {"ok": True, "attempts": attempts}
        except Exception as exc:
            attempts.append({"method": "SetInput", "frame": frame, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    try:
        inp = getattr(tool, name)
        if frame is None:
            setattr(tool, name, value)
        else:
            inp[int(frame)] = value
        attempts.append({"method": "attribute", "frame": frame, "ok": True, "value": value})
        return {"ok": True, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "attribute", "frame": frame, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    if frame is not None:
        try:
            inp = safe_call(tool, "FindInput", name, default=None)
            if inp is not None:
                inp[int(frame)] = value
                attempts.append({"method": "FindInput[index]", "frame": frame, "ok": True, "value": value})
                return {"ok": True, "attempts": attempts}
        except Exception as exc:
            attempts.append({"method": "FindInput[index]", "frame": frame, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return {"ok": False, "attempts": attempts}


def read_input(tool: Any, name: str, frame: Optional[int] = None) -> Dict[str, Any]:
    fn = getattr(tool, "GetInput", None)
    if callable(fn):
        try:
            value = fn(name) if frame is None else fn(name, int(frame))
            if value is not None:
                return {"ok": True, "value": json_safe(value), "method": "GetInput"}
        except Exception:
            pass
    try:
        inp = getattr(tool, name)
        value = inp if frame is None else inp[int(frame)]
        return {"ok": True, "value": json_safe(value), "method": "attribute"}
    except Exception:
        pass
    try:
        inp = safe_call(tool, "FindInput", name, default=None)
        if inp is not None:
            value = inp[0 if frame is None else int(frame)]
            return {"ok": True, "value": json_safe(value), "method": "FindInput"}
    except Exception:
        pass
    return {"ok": False, "value": None}


def numeric_close(actual: Any, expected: float, tolerance: float = 1e-4) -> bool:
    try:
        return abs(float(actual) - float(expected)) <= tolerance
    except (TypeError, ValueError):
        return False


def connect_tool(source: Any, dest: Any, input_name: str = "Input") -> Dict[str, Any]:
    attempts = []
    fn = getattr(dest, "ConnectInput", None)
    if callable(fn):
        for output in (source, safe_call(source, "FindMainOutput", 1, default=None)):
            if output is None:
                continue
            try:
                ok = fn(input_name, output)
                attempts.append({"method": "ConnectInput", "ok": bool(ok)})
                if ok:
                    return {"ok": True, "attempts": attempts}
            except Exception as exc:
                attempts.append({"method": "ConnectInput", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    try:
        inp = safe_call(dest, "FindInput", input_name, default=None)
        out = safe_call(source, "FindMainOutput", 1, default=None)
        if inp is not None and out is not None:
            ok = inp.ConnectTo(out)
            attempts.append({"method": "PlainInput.ConnectTo", "ok": bool(ok)})
            if ok:
                return {"ok": True, "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "PlainInput.ConnectTo", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return {"ok": False, "attempts": attempts}


def configure_flash(item: Any, spec: Mapping[str, Any], index: int) -> Dict[str, Any]:
    comp, comp_info = get_or_create_comp(item)
    row: Dict[str, Any] = {"comp": comp_info, "ok": False, "name": spec["name"]}
    if comp is None:
        row["error"] = "fusion_comp"
        return row
    locked = False
    try:
        if callable(getattr(comp, "Lock", None)):
            safe_call(comp, "Lock", default=None)
            locked = True
        media_out = find_tool(comp, "MediaOut")
        if media_out is None:
            media_out = safe_call(comp, "AddTool", "MediaOut", -32768, -32768, default=None)
        if media_out is None:
            row["error"] = "media_out"
            return row

        tool_name = f"{FLASH_TOOL_PREFIX}{index:03d}"
        background = find_named_tool(comp, tool_name)
        created = False
        if background is None:
            background = safe_call(comp, "AddTool", "Background", -32768, -32768, default=None)
            created = background is not None
            if background is not None and not set_tool_name(background, tool_name):
                row["error"] = "background_name"
                return row
        if background is None:
            row["error"] = "background"
            return row

        writes = {
            "red": set_input(background, "TopLeftRed", 1.0),
            "green": set_input(background, "TopLeftGreen", 1.0),
            "blue": set_input(background, "TopLeftBlue", 1.0),
        }
        alpha_modifier = ensure_bezier_modifier(comp, background, "TopLeftAlpha")
        keyframe_writes = []
        if alpha_modifier.get("ok"):
            for frame, value in spec["alpha_keyframes"]:
                keyframe_writes.append({
                    "frame": int(frame),
                    "value": float(value),
                    "write": write_animated_scalar(background, "TopLeftAlpha", int(frame), float(value)),
                })
        connection = connect_tool(background, media_out, "Input")

        readback = {
            "red": read_input(background, "TopLeftRed"),
            "green": read_input(background, "TopLeftGreen"),
            "blue": read_input(background, "TopLeftBlue"),
            "alpha_keyframes": [
                {"frame": int(frame), "expected": float(value), "readback": read_input(background, "TopLeftAlpha", int(frame))}
                for frame, value in spec["alpha_keyframes"]
            ],
        }
        colors_ok = all(
            readback[key].get("ok") and numeric_close(readback[key].get("value"), 1.0)
            for key in ("red", "green", "blue")
        )
        alpha_ok = all(
            item_row["readback"].get("ok")
            and numeric_close(item_row["readback"].get("value"), item_row["expected"])
            for item_row in readback["alpha_keyframes"]
        )
        writes_ok = (
            all(value.get("ok") for value in writes.values())
            and alpha_modifier.get("ok") is True
            and len(keyframe_writes) == len(spec["alpha_keyframes"])
            and all(item_row["write"].get("ok") for item_row in keyframe_writes)
        )
        row.update({
            "tool_name": tool_name,
            "background_created": created,
            "writes": writes,
            "alpha_modifier": alpha_modifier,
            "keyframe_writes": keyframe_writes,
            "connection": connection,
            "readback": readback,
            "colors_ok": colors_ok,
            "alpha_ok": alpha_ok,
            "ok": bool(writes_ok and connection.get("ok") and colors_ok and alpha_ok),
        })
        return row
    finally:
        if locked:
            safe_call(comp, "Unlock", default=None)


def flash_snapshot(timeline: Any, flashes: Sequence[Mapping[str, Any]], expected_track: int) -> Dict[str, Any]:
    expected_by_name = {str(row["name"]): row for row in flashes}
    found = []
    for track_index, item in all_video_items(timeline):
        name = item_name(item)
        if not name.startswith(FLASH_PREFIX):
            continue
        spec = expected_by_name.get(name)
        fusion = {"ok": False, "error": "unexpected_name"}
        if spec is not None:
            comp = safe_call(item, "GetFusionCompByIndex", 1, default=None)
            tool = find_named_tool(comp, f"{FLASH_TOOL_PREFIX}{list(expected_by_name).index(name)+1:03d}") if comp is not None else None
            if tool is not None:
                colors = {key: read_input(tool, input_name) for key, input_name in (
                    ("red", "TopLeftRed"), ("green", "TopLeftGreen"), ("blue", "TopLeftBlue")
                )}
                alpha = [
                    {"frame": int(frame), "expected": float(value), "readback": read_input(tool, "TopLeftAlpha", int(frame))}
                    for frame, value in spec["alpha_keyframes"]
                ]
                fusion = {
                    "tool_name": fusion_tool_name(tool),
                    "colors": colors,
                    "alpha_keyframes": alpha,
                    "ok": bool(
                        all(v.get("ok") and numeric_close(v.get("value"), 1.0) for v in colors.values())
                        and all(v["readback"].get("ok") and numeric_close(v["readback"].get("value"), v["expected"]) for v in alpha)
                    ),
                }
        row = {
            "name": name,
            "track_index": track_index,
            "start": item_start(item),
            "end": item_end(item),
            "duration": item_duration(item),
            "fusion": fusion,
        }
        if spec is not None:
            row["contract_ok"] = bool(
                track_index == expected_track
                and row["start"] == int(spec["start_frame"])
                and row["duration"] == int(spec["duration_frames"])
                and fusion.get("ok")
            )
        else:
            row["contract_ok"] = False
        found.append(row)
    found.sort(key=lambda row: (row["start"], row["name"]))
    return {
        "count": len(found),
        "expected_count": len(flashes),
        "track_index": expected_track,
        "rows": found,
        "names": [row["name"] for row in found],
        "ok": bool(
            len(found) == len(flashes)
            and set(row["name"] for row in found) == set(expected_by_name)
            and all(row.get("contract_ok") for row in found)
        ),
    }


def target_contract(
    source_snapshot: Mapping[str, Any],
    target: Any,
    flashes: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    target_captions = caption_snapshot(target)
    expected_track = int(source_snapshot["video_track_count"]) + 1
    flash = flash_snapshot(target, flashes, expected_track)
    return {
        "caption_snapshot": target_captions,
        "flash_snapshot": flash,
        "caption_count_ok": target_captions["count"] == EXPECTED_TEXTPLUS_COUNT,
        "caption_geometry_unchanged": target_captions["sha256"] == source_snapshot["sha256"],
        "track_count_ok": target_captions["video_track_count"] == expected_track,
        "ok": bool(
            target_captions["count"] == EXPECTED_TEXTPLUS_COUNT
            and target_captions["sha256"] == source_snapshot["sha256"]
            and target_captions["video_track_count"] == expected_track
            and flash["ok"]
        ),
    }


def cleanup_failed_duplicate(
    project_manager: Any,
    project: Any,
    media_pool: Any,
    source: Any,
    target_name: str,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"attempted": True, "errors": []}
    value, row = direct_call(project, "SetCurrentTimeline", source)
    result["restore_source"] = row
    if not value:
        result["errors"].append("restore_source")
    target = find_timeline(project, target_name)
    if target is not None:
        value, row = direct_call(media_pool, "DeleteTimelines", [target])
        result["delete_target"] = row
        if not value:
            result["errors"].append("delete_target")
    result["target_deleted"] = find_timeline(project, target_name) is None
    value, row = direct_call(project_manager, "SaveProject")
    result["save_cleanup"] = row
    if not value:
        result["errors"].append("save_cleanup")
    result["ok"] = not result["errors"] and result["target_deleted"]
    return result


def run(resolve: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    root = repository_root()
    command = context.get("command") if isinstance(context, Mapping) else None
    if not isinstance(command, Mapping):
        raise ValueError("command")
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    if command.get("task_id") != TASK_ID or command.get("mode") != MODE or not run_id:
        raise ValueError("command_identity")
    flash_config = command.get("flash")
    if not isinstance(flash_config, Mapping):
        raise ValueError("flash_config")
    run_mode = str(flash_config.get("run_mode") or "")
    if run_mode not in {"apply", "idempotency"}:
        raise ValueError("run_mode")

    report_dir = relative_path(root, command.get("artifacts_dir"))
    report_dir.mkdir(parents=True, exist_ok=True)
    plan_path = relative_path(root, flash_config.get("plan_path"))
    plan = load_json(plan_path)
    validate_plan(plan)
    flashes = list(plan["flashes"])

    report: Dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "version": VERSION,
        "run_id": run_id,
        "run_mode": run_mode,
        "ok": False,
        "started_at": utc_now(),
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "expected_textplus_count": EXPECTED_TEXTPLUS_COUNT,
        "expected_flash_count": len(flashes),
        "save_call_count": 0,
        "timeline_duplicate_count": 0,
        "video_track_add_count": 0,
        "flash_carrier_append_count": 0,
        "fusion_flash_configure_count": 0,
        "source_timeline_unchanged": False,
        "visual_approval_required": run_mode == "apply",
        "failures": [],
    }
    duplicate_created = False
    saved = False
    project_manager = project = media_pool = source = None
    try:
        source_contract = verify_source_contract(root, command)
        report["source_contract"] = source_contract

        project_manager = safe_call(resolve, "GetProjectManager", default=None)
        if project_manager is None:
            raise RuntimeError("project_manager")
        project = safe_call(project_manager, "GetCurrentProject", default=None)
        if project is None:
            raise RuntimeError("project")
        media_pool = safe_call(project, "GetMediaPool", default=None)
        if media_pool is None:
            raise RuntimeError("media_pool")

        source = find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        source_before = caption_snapshot(source)
        report["source_before"] = source_before
        if source_before["count"] != EXPECTED_TEXTPLUS_COUNT:
            raise RuntimeError(f"source_textplus_count:{source_before['count']}")

        existing_target = find_timeline(project, TARGET_TIMELINE_NAME)
        if run_mode == "idempotency":
            if existing_target is None:
                raise RuntimeError("idempotency_target_missing")
            target_before = target_contract(source_before, existing_target, flashes)
            report["target_before"] = target_before
            if not target_before["ok"]:
                raise RuntimeError("idempotency_target_contract")
            source_after = caption_snapshot(source)
            report["source_after"] = source_after
            report["source_timeline_unchanged"] = source_after["sha256"] == source_before["sha256"]
            report["target_after"] = target_contract(source_after, existing_target, flashes)
            report["idempotent"] = bool(
                report["source_timeline_unchanged"]
                and report["target_after"]["ok"]
                and report["save_call_count"] == 0
                and report["timeline_duplicate_count"] == 0
                and report["video_track_add_count"] == 0
                and report["flash_carrier_append_count"] == 0
                and report["fusion_flash_configure_count"] == 0
            )
            report["ok"] = report["idempotent"]
            if not report["ok"]:
                raise RuntimeError("idempotency_contract")
            report["finished_at"] = utc_now()
            write_json(report_dir / "flash_transition_application.json", report)
            return report

        if existing_target is not None:
            raise RuntimeError("target_exists")

        value, duplicate_call = direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
        target = value if value is not None else find_timeline(project, TARGET_TIMELINE_NAME)
        report["duplicate_call"] = duplicate_call
        if target is None:
            raise RuntimeError("duplicate_timeline")
        duplicate_created = True
        report["timeline_duplicate_count"] = 1
        if timeline_name(target) != TARGET_TIMELINE_NAME:
            raise RuntimeError("target_timeline_name")

        value, set_current = direct_call(project, "SetCurrentTimeline", target)
        report["set_current_target"] = set_current
        if not value:
            raise RuntimeError("set_current_target")

        duplicated_caption_snapshot = caption_snapshot(target)
        report["duplicate_caption_snapshot"] = duplicated_caption_snapshot
        if (
            duplicated_caption_snapshot["count"] != EXPECTED_TEXTPLUS_COUNT
            or duplicated_caption_snapshot["sha256"] != source_before["sha256"]
        ):
            raise RuntimeError("duplicate_caption_state")

        track_setup = ensure_extra_video_track(target, int(source_before["video_track_count"]))
        report["track_setup"] = track_setup
        if not track_setup["ok"]:
            raise RuntimeError("flash_track")
        report["video_track_add_count"] = 1
        flash_track = int(track_setup["target_track"])

        carrier = choose_carrier_source(target, 4)
        report["carrier_source"] = {k: json_safe(v) for k, v in carrier.items() if k not in {"item", "media_pool_item"}}
        if not carrier["ok"]:
            raise RuntimeError("carrier_source")

        append = append_flash_carriers(media_pool, target, carrier, flashes, flash_track)
        report["append"] = {k: json_safe(v) for k, v in append.items() if k != "assigned"}
        if not append["ok"]:
            raise RuntimeError("flash_append")
        report["flash_carrier_append_count"] = len(flashes)

        configure_rows = []
        for index, (spec, item) in enumerate(append["assigned"], start=1):
            row = configure_flash(item, spec, index)
            configure_rows.append(row)
            if not row.get("ok"):
                report["configure_rows"] = configure_rows
                raise RuntimeError(f"flash_fusion:{index}")
        report["configure_rows"] = configure_rows
        report["fusion_flash_configure_count"] = len(configure_rows)

        target_before_save = target_contract(source_before, target, flashes)
        report["target_before_save"] = target_before_save
        if not target_before_save["ok"]:
            raise RuntimeError("pre_save_target_contract")
        source_mid = caption_snapshot(source)
        report["source_mid"] = source_mid
        if source_mid["sha256"] != source_before["sha256"]:
            raise RuntimeError("source_changed_before_save")

        value, save_call = direct_call(project_manager, "SaveProject")
        report["save_call"] = save_call
        report["save_call_count"] = 1
        if not value:
            raise RuntimeError("save_project")
        saved = True

        persistent_target = find_timeline(project, TARGET_TIMELINE_NAME)
        if persistent_target is None:
            raise RuntimeError("persistent_target_missing")
        source_after = caption_snapshot(source)
        target_after = target_contract(source_after, persistent_target, flashes)
        report["source_after"] = source_after
        report["target_after"] = target_after
        report["source_timeline_unchanged"] = source_after["sha256"] == source_before["sha256"]
        report["persistent_readback_ok"] = bool(report["source_timeline_unchanged"] and target_after["ok"])
        report["ok"] = report["persistent_readback_ok"]
        if not report["ok"]:
            raise RuntimeError("persistent_readback")

        report["finished_at"] = utc_now()
        write_json(report_dir / "flash_transition_application.json", report)
        return report

    except BaseException as exc:
        report["failures"].append(f"{type(exc).__name__}: {exc}")
        report["traceback"] = traceback.format_exc()
        if duplicate_created and not saved and project_manager is not None and project is not None and media_pool is not None and source is not None:
            report["cleanup"] = cleanup_failed_duplicate(project_manager, project, media_pool, source, TARGET_TIMELINE_NAME)
            report["save_call_count"] += 1
        report["finished_at"] = utc_now()
        try:
            write_json(report_dir / "flash_transition_application.json", report)
        except Exception:
            pass
        return report
