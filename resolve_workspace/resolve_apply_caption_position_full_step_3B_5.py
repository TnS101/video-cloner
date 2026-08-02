#!/usr/bin/env python3
"""Video Cloner — Major Step 3B.5B full V3 source-position rollout.

Applies source-supported Text+ Center positions to all 116 V3 captions. Static
captions receive a direct Center value. The four Step 3C slide captions retain
their connected Path modifier: both Center keyframes are translated by the same
offset so relative motion is preserved.

Text, fonts, size, fill, glow/outline, timing, tracks, and all 16 Step 3C
animation targets are verified after save and object reacquisition. Failed runs
restore every attempted static Center or Center-keyframe pair.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

VERSION = "resolve_caption_position_step_3B_5B_v1_0_full_source_position_rollout"
DEFAULT_PROJECT_ROOT = r"C:\Users\User\Downloads\Projects\Video Cloner"
DEFAULT_VIDEO_ID = "DZsqH7auhjt"
DEFAULT_CONFIG_NAME = "resolve_caption_position_full_step_3B_5B_config.json"
V3_NAME_RE = re.compile(r"^VC_TEXTPLUS_(?P<index>\d+)_(?P<cue>sub_\d+)$", re.IGNORECASE)


def now_unix() -> float:
    return round(time.time(), 6)


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp.replace(path)


def canonical_hash(value: Dict[str, Any]) -> str:
    clean = dict(value)
    clean.pop("plan_hash", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def safe_call(obj: Any, method: str, *args: Any, default: Any = None) -> Any:
    if obj is None:
        return default
    fn = getattr(obj, method, None)
    if not callable(fn):
        return default
    try:
        return fn(*args)
    except Exception:
        return default


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(row) for key, row in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(row) for row in value]
    try:
        attrs = value.GetAttrs()
        if isinstance(attrs, dict):
            return {str(key): json_safe(row) for key, row in attrs.items()}
    except Exception:
        pass
    try:
        return str(value)
    except Exception:
        return repr(value)


def finite(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_token(value: Any) -> str:
    return "".join(ch.lower() for ch in normalize_text(value) if ch.isalnum())


def normalize_point(value: Any) -> Optional[List[float]]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        x, y = finite(value[0]), finite(value[1])
        if x is not None and y is not None:
            return [x, y]
    if isinstance(value, dict):
        x = value.get(1, value.get("1", value.get("x", value.get("X"))))
        y = value.get(2, value.get("2", value.get("y", value.get("Y"))))
        x, y = finite(x), finite(y)
        if x is not None and y is not None:
            return [x, y]
    return None


def values_match(actual: Any, expected: Any, tolerance: float = 1e-6) -> bool:
    expected_point = normalize_point(expected)
    if expected_point is not None:
        actual_point = normalize_point(actual)
        return bool(actual_point is not None and abs(actual_point[0] - expected_point[0]) <= tolerance and abs(actual_point[1] - expected_point[1]) <= tolerance)
    if isinstance(expected, str):
        return normalize_token(actual) == normalize_token(expected)
    expected_number = finite(expected)
    if expected_number is not None:
        actual_number = finite(actual)
        return actual_number is not None and abs(actual_number - expected_number) <= tolerance
    return json_safe(actual) == json_safe(expected)


def snapshots_match(actual: Any, expected: Any, tolerance: float = 1e-6) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual.keys()) != set(expected.keys()):
            return False
        return all(snapshots_match(actual.get(key), value, tolerance) for key, value in expected.items())
    if isinstance(expected, (list, tuple)):
        if not isinstance(actual, (list, tuple)) or len(actual) != len(expected):
            return False
        return all(snapshots_match(a, e, tolerance) for a, e in zip(actual, expected))
    return values_match(actual, expected, tolerance)


def default_config() -> Dict[str, Any]:
    root = Path(os.environ.get("VC_PROJECT_ROOT", DEFAULT_PROJECT_ROOT))
    video_id = os.environ.get("VC_VIDEO_ID", DEFAULT_VIDEO_ID)
    analysis = root / "data" / video_id / "analysis"
    davinci = root / "data" / video_id / "davinci"
    return {
        "project_root": str(root),
        "video_id": video_id,
        "plan_path": str(analysis / f"{video_id}_caption_position_full_plan_step_3B_5B.json"),
        "latest_report_path": str(davinci / f"{video_id}_resolve_position_full_step_3B_5B_report.json"),
        "first_report_path": str(davinci / f"{video_id}_resolve_position_full_step_3B_5B_first_application_report.json"),
        "idempotency_report_path": str(davinci / f"{video_id}_resolve_position_full_step_3B_5B_idempotency_report.json"),
        "state_path": str(davinci / f"{video_id}_resolve_position_full_step_3B_5B_state.json"),
        "workspace_status_path": str(davinci / f"{video_id}_resolve_position_full_step_3B_5B_workspace_status.json"),
        "workspace_log_path": str(davinci / f"{video_id}_resolve_position_full_step_3B_5B_workspace.log"),
        "workspace_lock_path": str(davinci / f"{video_id}_resolve_position_full_step_3B_5B_workspace.lock"),
        "expected_v3_count": 116,
        "value_tolerance": 1e-6,
        "animation_value_tolerance": 1e-5,
        "save_settle_sec": 1.5,
        "rollback_on_failure": True,
        "show_completion_message": True,
    }


def config_path() -> Path:
    env = os.environ.get("VC_STEP_3B5B_CONFIG")
    if env:
        return Path(env).expanduser().resolve()
    root = Path(os.environ.get("VC_PROJECT_ROOT", DEFAULT_PROJECT_ROOT))
    video_id = os.environ.get("VC_VIDEO_ID", DEFAULT_VIDEO_ID)
    return root / "data" / video_id / "davinci" / DEFAULT_CONFIG_NAME


def load_config() -> Tuple[Path, Dict[str, Any]]:
    path = config_path()
    cfg = default_config()
    if path.is_file():
        cfg.update(load_json(path))
    return path, cfg


def append_log(path: Path, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"timestamp_unix": now_unix(), "event": event, "version": VERSION}
        if payload:
            row.update(json_safe(payload))
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def show_message(title: str, message: str, error: bool = False) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, str(message), str(title), 0x10 if error else 0x40)
    except Exception:
        pass


def get_resolve() -> Any:
    injected = globals().get("resolve")
    if injected is not None:
        return injected
    bmd_obj = globals().get("bmd")
    if bmd_obj is not None:
        app = safe_call(bmd_obj, "scriptapp", "Resolve", default=None)
        if app is not None:
            return app
    try:
        import DaVinciResolveScript as dvr  # type: ignore
        app = dvr.scriptapp("Resolve")
        if app is not None:
            return app
    except Exception:
        pass
    raise RuntimeError("Resolve API unavailable. Run from Workspace -> Scripts.")


def item_name(item: Any) -> str:
    return normalize_text(safe_call(item, "GetName", default=""))


def item_start(item: Any) -> Optional[int]:
    value = finite(safe_call(item, "GetStart", default=None))
    return int(round(value)) if value is not None else None


def item_end(item: Any) -> Optional[int]:
    value = finite(safe_call(item, "GetEnd", default=None))
    return int(round(value)) if value is not None else None


def track_items(timeline: Any, track_type: str, index: int) -> List[Any]:
    rows = safe_call(timeline, "GetItemListInTrack", track_type, int(index), default=[]) or []
    if isinstance(rows, dict):
        rows = list(rows.values())
    return list(rows)


def scan_tracks(timeline: Any) -> Dict[str, List[Dict[str, Any]]]:
    snapshot: Dict[str, List[Dict[str, Any]]] = {}
    for track_type, prefix in (("video", "V"), ("audio", "A")):
        count = int(safe_call(timeline, "GetTrackCount", track_type, default=0) or 0)
        for index in range(1, count + 1):
            snapshot[f"{prefix}{index}"] = [{"name": item_name(item), "start": item_start(item), "end": item_end(item)} for item in track_items(timeline, track_type, index)]
    return snapshot


def scan_v3(timeline: Any) -> Dict[str, Any]:
    found: Dict[str, Any] = {}
    count = int(safe_call(timeline, "GetTrackCount", "video", default=0) or 0)
    for index in range(1, count + 1):
        for item in track_items(timeline, "video", index):
            name = item_name(item)
            if V3_NAME_RE.match(name):
                found[name] = item
    return found


def v3_ranges(items: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sorted(({"name": name, "start": item_start(item), "end": item_end(item)} for name, item in items.items()), key=lambda row: (row["start"], row["end"], row["name"]))


def fusion_comp(item: Any) -> Any:
    comp = safe_call(item, "GetFusionCompByIndex", 1, default=None)
    if comp is not None:
        return comp
    for name in safe_call(item, "GetFusionCompNameList", default=[]) or []:
        comp = safe_call(item, "GetFusionCompByName", name, default=None)
        if comp is not None:
            return comp
    return None


def textplus_tool(comp: Any) -> Any:
    tools = safe_call(comp, "GetToolList", False, "TextPlus", default={}) or {}
    if isinstance(tools, dict) and tools:
        return next(iter(tools.values()))
    tools = safe_call(comp, "GetToolList", False, default={}) or {}
    if isinstance(tools, dict):
        for tool in tools.values():
            attrs = safe_call(tool, "GetAttrs", default={}) or {}
            if str(attrs.get("TOOLS_RegID") or "").lower() == "textplus":
                return tool
    return None


def find_input(tool: Any, input_name: str) -> Any:
    obj = safe_call(tool, "FindInput", input_name, default=None)
    if obj is not None:
        return obj
    try:
        obj = getattr(tool, input_name)
        if obj is not None:
            return obj
    except Exception:
        pass
    raw = safe_call(tool, "GetInputList", default={}) or {}
    entries: Iterable[Any] = raw.items() if isinstance(raw, dict) else enumerate(raw or [])
    for key, row in entries:
        attrs = safe_call(row, "GetAttrs", default={}) or {}
        candidate = str(attrs.get("INPS_ID") or attrs.get("INPS_Name") or key or "")
        if candidate.lower() == input_name.lower():
            return row
    return None


def connected_output(input_object: Any) -> Any:
    return safe_call(input_object, "GetConnectedOutput", default=None)


def read_input(tool: Any, input_name: str, frame: Optional[int] = None) -> Any:
    value = safe_call(tool, "GetInput", input_name, default=None) if frame is None else safe_call(tool, "GetInput", input_name, int(frame), default=None)
    if value is not None:
        return value
    obj = find_input(tool, input_name)
    if obj is not None:
        try:
            return obj[int(frame or 0)]
        except Exception:
            pass
    return None


def point_representations(point: Sequence[float]) -> List[Any]:
    x, y = float(point[0]), float(point[1])
    values: List[Any] = []
    bmd_obj = globals().get("bmd")
    if bmd_obj is not None:
        try:
            values.append(bmd_obj.Point(x, y))
        except Exception:
            pass
    values.extend(([x, y], {1: x, 2: y, 3: 0.0}))
    return values


def write_static_point(tool: Any, input_name: str, expected: Sequence[float], tolerance: float) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    for representation in point_representations(expected):
        try:
            returned = tool.SetInput(input_name, representation)
            actual = read_input(tool, input_name)
            matched = values_match(actual, expected, tolerance)
            attempts.append({"method": "Tool.SetInput", "representation": type(representation).__name__, "returned": json_safe(returned), "actual": json_safe(actual), "matched": matched})
            if matched:
                return {"ok": True, "input": input_name, "expected": list(expected), "actual": json_safe(actual), "attempts": attempts}
        except Exception as exc:
            attempts.append({"method": "Tool.SetInput", "representation": type(representation).__name__, "error": f"{type(exc).__name__}: {exc}"})
    for representation in point_representations(expected):
        try:
            setattr(tool, input_name, representation)
            actual = read_input(tool, input_name)
            matched = values_match(actual, expected, tolerance)
            attempts.append({"method": "setattr", "representation": type(representation).__name__, "actual": json_safe(actual), "matched": matched})
            if matched:
                return {"ok": True, "input": input_name, "expected": list(expected), "actual": json_safe(actual), "attempts": attempts}
        except Exception as exc:
            attempts.append({"method": "setattr", "representation": type(representation).__name__, "error": f"{type(exc).__name__}: {exc}"})
    return {"ok": False, "input": input_name, "expected": list(expected), "actual": json_safe(read_input(tool, input_name)), "attempts": attempts}


def write_point_key(tool: Any, input_name: str, frame: int, expected: Sequence[float], tolerance: float) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    input_object = find_input(tool, input_name)
    for representation in point_representations(expected):
        if input_object is not None:
            try:
                input_object[int(frame)] = representation
                actual = read_input(tool, input_name, int(frame))
                matched = values_match(actual, expected, tolerance)
                attempts.append({"method": "Input[frame]=value", "frame": int(frame), "representation": type(representation).__name__, "actual": json_safe(actual), "matched": matched})
                if matched:
                    return {"ok": True, "input": input_name, "frame": int(frame), "expected": list(expected), "actual": json_safe(actual), "attempts": attempts}
            except Exception as exc:
                attempts.append({"method": "Input[frame]=value", "frame": int(frame), "representation": type(representation).__name__, "error": f"{type(exc).__name__}: {exc}"})
        try:
            returned = tool.SetInput(input_name, representation, int(frame))
            actual = read_input(tool, input_name, int(frame))
            matched = values_match(actual, expected, tolerance)
            attempts.append({"method": "Tool.SetInput(frame)", "frame": int(frame), "representation": type(representation).__name__, "returned": json_safe(returned), "actual": json_safe(actual), "matched": matched})
            if matched:
                return {"ok": True, "input": input_name, "frame": int(frame), "expected": list(expected), "actual": json_safe(actual), "attempts": attempts}
        except Exception as exc:
            attempts.append({"method": "Tool.SetInput(frame)", "frame": int(frame), "representation": type(representation).__name__, "error": f"{type(exc).__name__}: {exc}"})
    return {"ok": False, "input": input_name, "frame": int(frame), "expected": list(expected), "actual": json_safe(read_input(tool, input_name, int(frame))), "attempts": attempts}


def read_candidates(tool: Any, candidates: Sequence[str]) -> Dict[str, Any]:
    for name in candidates:
        if find_input(tool, name) is None:
            continue
        return {"resolved_input": name, "value": json_safe(read_input(tool, name))}
    return {"resolved_input": None, "value": None}


def identity_snapshot(item: Any, tool: Any) -> Dict[str, Any]:
    return {
        "name": item_name(item), "start": item_start(item), "end": item_end(item),
        "text": str(read_input(tool, "StyledText") or ""),
        "font": str(read_input(tool, "Font") or ""), "style": str(read_input(tool, "Style") or ""),
    }


def fill_snapshot(tool: Any) -> Dict[str, Any]:
    return {name: json_safe(read_input(tool, name)) for name in ("Enabled1", "Red1", "Green1", "Blue1", "Alpha1")}


def size_snapshot(tool: Any) -> Dict[str, Any]:
    obj = find_input(tool, "Size")
    return {"value": json_safe(read_input(tool, "Size")), "modifier_connected": connected_output(obj) is not None}


def layout_without_center_snapshot(tool: Any) -> Dict[str, Any]:
    names = ("LayoutType", "HAnchor", "VAnchor", "Angle", "CharacterSpacing", "LineSpacing", "Width", "Height", "UseFrameFormatSettings")
    return {name: json_safe(read_input(tool, name)) for name in names if find_input(tool, name) is not None}


def shading_snapshot(tool: Any) -> Dict[str, Any]:
    return {
        "outline": {
            "Enabled2": read_candidates(tool, ("Enabled2",)), "ElementShape2": read_candidates(tool, ("ElementShape2", "Appearance2")),
            "Red2": read_candidates(tool, ("Red2",)), "Green2": read_candidates(tool, ("Green2",)), "Blue2": read_candidates(tool, ("Blue2",)),
            "Alpha2": read_candidates(tool, ("Alpha2", "Opacity2")), "Thickness2": read_candidates(tool, ("Thickness2",)),
            "OutsideOnly2": read_candidates(tool, ("OutsideOnly2",)),
        },
        "shadow": {
            "Enabled3": read_candidates(tool, ("Enabled3",)), "ElementShape3": read_candidates(tool, ("ElementShape3", "Appearance3")),
            "Red3": read_candidates(tool, ("Red3",)), "Green3": read_candidates(tool, ("Green3",)), "Blue3": read_candidates(tool, ("Blue3",)),
            "Opacity3": read_candidates(tool, ("Opacity3", "Alpha3")), "Offset3": read_candidates(tool, ("Offset3",)),
            "SoftnessX3": read_candidates(tool, ("SoftnessX3", "Softness3")), "SoftnessY3": read_candidates(tool, ("SoftnessY3",)),
        },
    }


def animation_snapshot(tool: Any, targets: Sequence[Dict[str, Any]], tolerance: float) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for target in targets:
        input_name = str(target.get("input") or "")
        frame = int(target.get("local_frame") or 0)
        expected = target.get("expected")
        input_object = find_input(tool, input_name)
        connected = connected_output(input_object) is not None
        actual = read_input(tool, input_name, frame)
        matched = values_match(actual, expected, tolerance)
        rows.append({
            "input": input_name, "local_frame": frame, "expected": json_safe(expected), "actual": json_safe(actual),
            "modifier_connected": connected, "matched": matched, "present": bool(connected and matched),
        })
    return rows


def item_snapshot(item: Any, tool: Any, animation_targets: Sequence[Dict[str, Any]], animation_tolerance: float) -> Dict[str, Any]:
    center_obj = find_input(tool, "Center")
    return {
        "identity": identity_snapshot(item, tool),
        "center": json_safe(read_input(tool, "Center")),
        "center_modifier_connected": connected_output(center_obj) is not None,
        "size": size_snapshot(tool),
        "fill": fill_snapshot(tool),
        "layout_without_center": layout_without_center_snapshot(tool),
        "shading": shading_snapshot(tool),
        "animation": animation_snapshot(tool, animation_targets, animation_tolerance),
    }


def acquire_all(timeline: Any, expected_v3: int) -> Dict[str, Tuple[Any, Any, Any]]:
    v3 = scan_v3(timeline)
    if len(v3) != expected_v3:
        raise RuntimeError(f"Expected {expected_v3} V3 Text+ items, found {len(v3)}")
    acquired: Dict[str, Tuple[Any, Any, Any]] = {}
    for name, item in v3.items():
        comp = fusion_comp(item)
        tool = textplus_tool(comp)
        if comp is None or tool is None:
            raise RuntimeError(f"Text+ tool unavailable: {name}")
        acquired[name] = (item, comp, tool)
    return acquired


def write_status(path: Path, base: Dict[str, Any], stage: str, current: int, total: int, item: Optional[str] = None) -> None:
    payload = dict(base)
    payload.update({
        "running": True, "stage": stage, "updated_at_unix": now_unix(),
        "progress": {"current": int(current), "total": int(total), "percent": round(100.0 * current / total, 1) if total else 0.0, "item": item},
    })
    write_json(path, payload)


def target_position_is_correct(tool: Any, plan_item: Dict[str, Any], tolerance: float) -> bool:
    mode = str(plan_item.get("position_write_mode") or "")
    if mode == "static_center":
        center_obj = find_input(tool, "Center")
        return connected_output(center_obj) is None and values_match(read_input(tool, "Center"), plan_item.get("target_center"), tolerance)
    if mode == "translated_center_animation":
        targets = [row for row in (plan_item.get("expected_animation_targets_after") or []) if row.get("input") == "Center"]
        snap = animation_snapshot(tool, targets, tolerance)
        return len(snap) == 2 and all(row.get("present") for row in snap)
    return False


def write_position(comp: Any, tool: Any, plan_item: Dict[str, Any], tolerance: float) -> Dict[str, Any]:
    mode = str(plan_item.get("position_write_mode") or "")
    safe_call(comp, "Lock", default=None)
    try:
        if mode == "static_center":
            result = write_static_point(tool, "Center", plan_item.get("target_center") or [], tolerance)
            result["write_mode"] = mode
            return result
        if mode == "translated_center_animation":
            center_obj = find_input(tool, "Center")
            if connected_output(center_obj) is None:
                return {"ok": False, "write_mode": mode, "failure": "center_modifier_not_connected", "writes": []}
            writes = []
            for target in plan_item.get("expected_animation_targets_after") or []:
                if target.get("input") != "Center":
                    continue
                writes.append(write_point_key(tool, "Center", int(target.get("local_frame") or 0), target.get("expected") or [], tolerance))
            return {"ok": len(writes) == 2 and all(row.get("ok") for row in writes), "write_mode": mode, "writes": writes}
        return {"ok": False, "write_mode": mode, "failure": "unknown_position_write_mode"}
    finally:
        safe_call(comp, "Unlock", default=None)


def restore_position(comp: Any, tool: Any, plan_item: Dict[str, Any], baseline: Dict[str, Any], tolerance: float) -> Dict[str, Any]:
    mode = str(plan_item.get("position_write_mode") or "")
    safe_call(comp, "Lock", default=None)
    try:
        if mode == "static_center":
            point = normalize_point(baseline.get("center"))
            return write_static_point(tool, "Center", point or [], tolerance) if point is not None else {"ok": False, "failure": "baseline_center_invalid"}
        if mode == "translated_center_animation":
            writes = []
            for target in plan_item.get("protected_animation_targets_before") or []:
                if target.get("input") != "Center":
                    continue
                writes.append(write_point_key(tool, "Center", int(target.get("local_frame") or 0), target.get("expected") or [], tolerance))
            return {"ok": len(writes) == 2 and all(row.get("ok") for row in writes), "writes": writes}
        return {"ok": False, "failure": "unknown_position_write_mode"}
    finally:
        safe_call(comp, "Unlock", default=None)


def run() -> Dict[str, Any]:
    started = time.time()
    cfg_path, cfg = load_config()
    plan_path = Path(cfg["plan_path"])
    latest_path = Path(cfg["latest_report_path"])
    first_path = Path(cfg["first_report_path"])
    idempotency_path = Path(cfg["idempotency_report_path"])
    state_path = Path(cfg["state_path"])
    status_path = Path(cfg["workspace_status_path"])
    log_path = Path(cfg["workspace_log_path"])
    lock_path = Path(cfg["workspace_lock_path"])
    expected_v3 = int(cfg.get("expected_v3_count") or 116)
    tolerance = max(float(cfg.get("value_tolerance") or 1e-6), 1e-6)
    animation_tolerance = max(float(cfg.get("animation_value_tolerance") or 1e-5), 1e-5)
    settle = max(float(cfg.get("save_settle_sec") or 1.5), 0.1)
    run_id = f"{int(time.time())}-{os.getpid()}"

    report: Dict[str, Any] = {
        "ok": False, "step": "Major Step 3B.5B", "workspace_version": VERSION,
        "config": str(cfg_path), "plan": str(plan_path), "latest_report": str(latest_path),
        "first_application_report": str(first_path), "idempotency_report": str(idempotency_path),
        "state": str(state_path), "failures": [], "warnings": [],
    }

    missing = []
    if not cfg_path.is_file():
        missing.append("missing_prepared_config")
    if not plan_path.is_file():
        missing.append("missing_prepared_plan")
    if missing:
        report.update({"run_mode": "precondition_failed", "failures": missing, "writes_attempted": False, "remediation": "Run run_prepare_DZsqH7auhjt_STEP_3B_5B.bat and continue only after PASS."})
        latest_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(latest_path, report)
        status = {"ok": False, "running": False, "step": "Major Step 3B.5B", "version": VERSION, "run_id": run_id, "return_code": 2, "run_mode": "precondition_failed", "report": str(latest_path), "failures": missing, "writes_attempted": False}
        write_json(status_path, status)
        append_log(log_path, "workspace_precondition_failed", status)
        return report

    if lock_path.exists():
        report.update({"run_mode": "already_running", "failures": ["workspace_already_running"]})
        write_json(latest_path, report)
        return report

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(lock_path, {"run_id": run_id, "started_at_unix": now_unix(), "version": VERSION})
    status_base = {"ok": False, "running": True, "step": "Major Step 3B.5B", "version": VERSION, "run_id": run_id, "started_at_unix": now_unix(), "report": str(latest_path)}
    write_status(status_path, status_base, "starting", 0, expected_v3)
    append_log(log_path, "workspace_started", status_base)

    try:
        plan = load_json(plan_path)
        if not plan.get("ok") or canonical_hash(plan) != plan.get("plan_hash"):
            raise RuntimeError("Step 3B.5B plan is invalid or hash-mismatched")
        items = [row for row in (plan.get("items") or []) if isinstance(row, dict) and row.get("rollout_target")]
        if len(items) != expected_v3:
            raise RuntimeError(f"Expected {expected_v3} rollout items, found {len(items)}")
        plan_hash = str(plan.get("plan_hash"))
        previous_state = load_json(state_path) if state_path.is_file() else {}
        state_valid = bool(previous_state.get("ok") and previous_state.get("plan_hash") == plan_hash)
        run_mode = "idempotent_second_run" if state_valid else "first_application"
        mode_path = idempotency_path if state_valid else first_path
        report.update({"run_mode": run_mode, "mode_report": str(mode_path), "plan_hash": plan_hash})

        resolve_app = get_resolve()
        manager = safe_call(resolve_app, "GetProjectManager", default=None)
        project = safe_call(manager, "GetCurrentProject", default=None)
        timeline = safe_call(project, "GetCurrentTimeline", default=None)
        if manager is None or project is None or timeline is None:
            raise RuntimeError("Resolve project/timeline unavailable")

        tracks_before = scan_tracks(timeline)
        write_status(status_path, status_base, "acquire_v3", 0, expected_v3)
        live = acquire_all(timeline, expected_v3)
        ranges_before = v3_ranges({name: row[0] for name, row in live.items()})

        baselines: Dict[str, Any] = {}
        before_status: Dict[str, bool] = {}
        preflight_failures: List[str] = []
        for index, plan_item in enumerate(items, 1):
            name = str(plan_item.get("name") or "")
            if name not in live:
                preflight_failures.append(f"missing_v3_item:{name}")
                continue
            item, _comp, tool = live[name]
            pre_targets = plan_item.get("expected_animation_targets_after") if state_valid else plan_item.get("protected_animation_targets_before")
            snap = item_snapshot(item, tool, pre_targets or [], animation_tolerance)
            baselines[name] = snap
            before_status[name] = target_position_is_correct(tool, plan_item, tolerance)
            identity = snap["identity"]
            if identity.get("name") != name or identity.get("start") != int(plan_item.get("start") or 0) or identity.get("end") != int(plan_item.get("end") or 0):
                preflight_failures.append(f"identity_preflight:{name}")
            if normalize_token(identity.get("text")) != normalize_token(plan_item.get("text")):
                preflight_failures.append(f"text_preflight:{name}")
            if normalize_token(identity.get("font")) != normalize_token(plan_item.get("expected_font_family")) or normalize_token(identity.get("style")) != normalize_token(plan_item.get("expected_font_face")):
                preflight_failures.append(f"font_preflight:{name}")
            if str(plan_item.get("position_write_mode")) == "translated_center_animation":
                if not snap.get("center_modifier_connected"):
                    preflight_failures.append(f"center_modifier_missing:{name}")
            elif snap.get("center_modifier_connected"):
                preflight_failures.append(f"unexpected_center_modifier:{name}")
            if not all(row.get("present") for row in snap["animation"]):
                preflight_failures.append(f"animation_preflight:{name}")
            if index == 1 or index % 5 == 0 or index == expected_v3:
                write_status(status_path, status_base, "preflight", index, expected_v3, name)

        if preflight_failures:
            report.update({"run_mode": "preflight_failed", "failures": preflight_failures, "preflight": {"writes_attempted": False}})
            raise StopIteration

        modified_names: List[str] = []
        attempted_names: List[str] = []
        item_results: List[Dict[str, Any]] = []
        for index, plan_item in enumerate(items, 1):
            name = str(plan_item.get("name"))
            _item, comp, tool = live[name]
            if before_status[name]:
                write = {"ok": True, "write_mode": "not_required_already_correct"}
                modified = False
            else:
                attempted_names.append(name)
                write = write_position(comp, tool, plan_item, tolerance)
                modified = bool(write.get("ok"))
                if modified:
                    modified_names.append(name)
            item_results.append({
                "name": name, "cue_id": plan_item.get("cue_id"), "source_position": plan_item.get("source_position"),
                "target_center": plan_item.get("target_center"), "position_write_mode": plan_item.get("position_write_mode"),
                "already_correct_before": before_status[name], "modified": modified, "write": write,
            })
            if not write.get("ok"):
                report["failures"].append(f"position_write_failed:{name}")
                break
            if index == 1 or index % 5 == 0 or index == expected_v3:
                write_status(status_path, status_base, "apply_positions", index, expected_v3, name)

        save_ok = False
        if not report["failures"]:
            write_status(status_path, status_base, "save_after_write", expected_v3, expected_v3)
            returned = safe_call(manager, "SaveProject", default=False)
            save_ok = returned is not False
            time.sleep(settle)
            if not save_ok:
                report["failures"].append("project_save_failed")

        timeline_after = safe_call(project, "GetCurrentTimeline", default=None)
        live_after = acquire_all(timeline_after, expected_v3) if timeline_after is not None else {}
        persistent_failures: List[str] = []
        position_verified = static_verified = translated_caption_verified = translated_keyframe_verified = 0
        fill_verified = effect_verified = size_verified = identity_verified = layout_verified = 0
        animation_target_verified = 0
        source_verified = {
            "caption_style_event.placement.anchor": 0,
            "classified_caption_group.center_near_cue_time": 0,
            "interpolated_between_direct_event_anchors": 0,
            "nearest_direct_event_anchor": 0,
        }
        identity_failures = style_failures = layout_failures = animation_failures = 0

        if not report["failures"]:
            for index, plan_item in enumerate(items, 1):
                name = str(plan_item.get("name"))
                item_after, _comp_after, tool_after = live_after[name]
                after = item_snapshot(item_after, tool_after, plan_item.get("expected_animation_targets_after") or [], animation_tolerance)
                before = baselines[name]
                position_ok = target_position_is_correct(tool_after, plan_item, tolerance)
                if position_ok:
                    position_verified += 1
                    source = str((plan_item.get("source_position") or {}).get("source") or "")
                    if source in source_verified:
                        source_verified[source] += 1
                    if plan_item.get("position_write_mode") == "static_center":
                        static_verified += 1
                    else:
                        translated_caption_verified += 1
                        translated_keyframe_verified += sum(1 for row in after["animation"] if row.get("input") == "Center" and row.get("present"))
                else:
                    persistent_failures.append(f"position_persistence:{name}")

                if snapshots_match(after["identity"], before["identity"], tolerance):
                    identity_verified += 1
                else:
                    identity_failures += 1
                    persistent_failures.append(f"identity_changed:{name}")
                if snapshots_match(after["fill"], before["fill"], tolerance):
                    fill_verified += 1
                else:
                    style_failures += 1
                    persistent_failures.append(f"fill_changed:{name}")
                if snapshots_match(after["shading"], before["shading"], tolerance):
                    effect_verified += 1
                else:
                    style_failures += 1
                    persistent_failures.append(f"effects_changed:{name}")
                if snapshots_match(after["size"], before["size"], tolerance):
                    size_verified += 1
                else:
                    style_failures += 1
                    persistent_failures.append(f"size_changed:{name}")
                if snapshots_match(after["layout_without_center"], before["layout_without_center"], tolerance):
                    layout_verified += 1
                else:
                    layout_failures += 1
                    persistent_failures.append(f"layout_changed:{name}")
                present_count = sum(1 for row in after["animation"] if row.get("present"))
                animation_target_verified += present_count
                if present_count != len(after["animation"]):
                    animation_failures += 1
                    persistent_failures.append(f"animation_changed:{name}")
                if index == 1 or index % 5 == 0 or index == expected_v3:
                    write_status(status_path, status_base, "persistent_verification", index, expected_v3, name)
            report["failures"].extend(persistent_failures)

        tracks_after = scan_tracks(timeline_after) if timeline_after is not None else {}
        ranges_after = v3_ranges({name: row[0] for name, row in live_after.items()}) if live_after else []
        track_integrity_ok = snapshots_match(tracks_after, tracks_before, tolerance)
        v3_integrity_ok = snapshots_match(ranges_after, ranges_before, tolerance)
        if not track_integrity_ok:
            report["failures"].append("timeline_track_integrity_failed")
        if not v3_integrity_ok:
            report["failures"].append("v3_track_integrity_failed")

        rollback = {"attempted": False, "ok": None}
        if report["failures"] and cfg.get("rollback_on_failure", True) and attempted_names:
            rollback["attempted"] = True
            rollback_rows = []
            current_live = acquire_all(safe_call(project, "GetCurrentTimeline", default=None), expected_v3)
            plan_by_name = {str(row.get("name")): row for row in items}
            for name in attempted_names:
                _item, comp, tool = current_live[name]
                rollback_rows.append({"name": name, "result": restore_position(comp, tool, plan_by_name[name], baselines[name], tolerance)})
            rollback_save = safe_call(manager, "SaveProject", default=False) is not False
            time.sleep(settle)
            rollback.update({"items": rollback_rows, "save_ok": rollback_save, "ok": bool(rollback_save and all(row["result"].get("ok") for row in rollback_rows))})

        plan_summary = plan.get("summary") or {}
        expected_animation_targets = int(plan_summary.get("animation_target_count_after") or 0)
        summary = {
            "v3_candidate_count": expected_v3,
            "plan_item_count": len(items),
            "rollout_target_count": len(items),
            "direct_event_position_count": int(plan_summary.get("direct_event_position_count") or 0),
            "near_group_position_count": int(plan_summary.get("near_group_position_count") or 0),
            "interpolated_position_count": int(plan_summary.get("interpolated_position_count") or 0),
            "nearest_event_position_count": int(plan_summary.get("nearest_event_position_count") or 0),
            "mapped_count": len(live),
            "modified_count": len(modified_names),
            "already_correct_count": sum(1 for value in before_status.values() if value),
            "position_requested_count": len(items),
            "position_verified_count": position_verified,
            "static_position_count": int(plan_summary.get("static_center_caption_count") or 0),
            "static_position_verified_count": static_verified,
            "translated_center_animation_caption_count": int(plan_summary.get("translated_center_animation_caption_count") or 0),
            "translated_center_animation_verified_count": translated_caption_verified,
            "translated_center_keyframe_count": int(plan_summary.get("translated_center_keyframe_count") or 0),
            "translated_center_keyframe_verified_count": translated_keyframe_verified,
            "direct_event_position_verified_count": source_verified["caption_style_event.placement.anchor"],
            "near_group_position_verified_count": source_verified["classified_caption_group.center_near_cue_time"],
            "interpolated_position_verified_count": source_verified["interpolated_between_direct_event_anchors"],
            "nearest_event_position_verified_count": source_verified["nearest_direct_event_anchor"],
            "protected_fill_count": expected_v3,
            "protected_fill_verified_count": fill_verified,
            "protected_effect_count": expected_v3,
            "protected_effect_verified_count": effect_verified,
            "protected_size_count": expected_v3,
            "protected_size_verified_count": size_verified,
            "protected_identity_count": expected_v3,
            "protected_identity_verified_count": identity_verified,
            "protected_layout_count": expected_v3,
            "protected_layout_verified_count": layout_verified,
            "expected_animation_target_count": expected_animation_targets,
            "expected_animation_target_verified_count": animation_target_verified,
            "identity_integrity_failure_count": identity_failures,
            "style_integrity_failure_count": style_failures,
            "layout_integrity_failure_count": layout_failures,
            "animation_integrity_failure_count": animation_failures,
            "timeline_integrity_failure_count": (0 if track_integrity_ok else 1) + (0 if v3_integrity_ok else 1),
            "rollback_performed_count": 1 if rollback["attempted"] else 0,
            "failed_count": len(report["failures"]),
        }
        ok = not report["failures"]
        report.update({
            "ok": ok, "project_name": safe_call(project, "GetName", default=None), "timeline_name": safe_call(timeline_after, "GetName", default=None),
            "summary": summary, "items": item_results,
            "track_integrity": {"ok": track_integrity_ok, "before": tracks_before, "after": tracks_after},
            "v3_track_integrity": {"ok": v3_integrity_ok, "before": ranges_before, "after": ranges_after},
            "rollback": rollback, "runtime_seconds": round(time.time() - started, 3),
        })
        write_json(latest_path, report)
        write_json(mode_path, report)
        if ok:
            write_json(state_path, {"ok": True, "step": "Major Step 3B.5B", "workspace_version": VERSION, "plan_hash": plan_hash, "last_run_mode": run_mode, "last_report": str(mode_path), "updated_at_unix": now_unix()})

        status = {"ok": ok, "running": False, "step": "Major Step 3B.5B", "version": VERSION, "run_id": run_id, "finished_at_unix": now_unix(), "return_code": 0 if ok else 1, "run_mode": run_mode, "report": str(latest_path), "mode_report": str(mode_path), "summary": summary, "failures": report["failures"]}
        write_json(status_path, status)
        append_log(log_path, "workspace_finished", status)
        return report

    except StopIteration:
        report["runtime_seconds"] = round(time.time() - started, 3)
        write_json(latest_path, report)
        status = {"ok": False, "running": False, "step": "Major Step 3B.5B", "version": VERSION, "run_id": run_id, "finished_at_unix": now_unix(), "return_code": 2, "run_mode": report.get("run_mode"), "report": str(latest_path), "failures": report.get("failures") or []}
        write_json(status_path, status)
        append_log(log_path, "workspace_preflight_failed", status)
        return report
    except Exception as exc:
        report.update({"ok": False, "run_mode": "exception", "failures": ["workspace_exception"], "exception": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(), "runtime_seconds": round(time.time() - started, 3)})
        write_json(latest_path, report)
        status = {"ok": False, "running": False, "step": "Major Step 3B.5B", "version": VERSION, "run_id": run_id, "finished_at_unix": now_unix(), "return_code": 1, "run_mode": "exception", "report": str(latest_path), "exception": report["exception"], "traceback": report["traceback"]}
        write_json(status_path, status)
        append_log(log_path, "workspace_exception", status)
        return report
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass


def main() -> None:
    report = run()
    summary = report.get("summary") or {}
    if report.get("ok"):
        show_message(
            "Video Cloner — Step 3B.5B full position rollout complete",
            "Full V3 source-position rollout finished.\n\n"
            f"V3 clips: {summary.get('v3_candidate_count', 0)}\n"
            f"Direct anchors: {summary.get('direct_event_position_count', 0)}\n"
            f"Near-time groups: {summary.get('near_group_position_count', 0)}\n"
            f"Interpolated: {summary.get('interpolated_position_count', 0)}\n"
            f"Nearest fallback: {summary.get('nearest_event_position_count', 0)}\n"
            f"Modified: {summary.get('modified_count', 0)}\n"
            f"Already correct: {summary.get('already_correct_count', 0)}\n"
            f"Positions verified: {summary.get('position_verified_count', 0)}/{summary.get('position_requested_count', 0)}\n"
            f"Slide animations translated: {summary.get('translated_center_animation_verified_count', 0)}/{summary.get('translated_center_animation_caption_count', 0)}\n"
            f"Style preserved: {summary.get('protected_fill_verified_count', 0)}/{summary.get('protected_fill_count', 0)}\n"
            f"Animation targets verified: {summary.get('expected_animation_target_verified_count', 0)}/{summary.get('expected_animation_target_count', 0)}\n"
            f"Failures: {summary.get('failed_count', 0)}\n\n"
            f"Mode report:\n{report.get('mode_report')}",
            error=False,
        )
    else:
        if report.get("run_mode") == "precondition_failed":
            message = "Step 3B.5B was not prepared. No Resolve writes were attempted.\n\nFailures:\n- " + "\n- ".join(report.get("failures") or ["missing preparation output"]) + "\n\nRun run_prepare_DZsqH7auhjt_STEP_3B_5B.bat and continue only after PASS."
        else:
            message = "The full position rollout did not pass.\n\nFailures:\n- " + "\n- ".join(report.get("failures") or [report.get("exception") or "unknown failure"]) + f"\n\nReport:\n{report.get('latest_report')}"
        show_message("Video Cloner — Step 3B.5B full position rollout failed", message, error=True)


_AUTORUN_DONE = False


def _workspace_autorun() -> None:
    global _AUTORUN_DONE
    if _AUTORUN_DONE:
        return
    _AUTORUN_DONE = True
    main()


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1":
    _workspace_autorun()
