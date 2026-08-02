#!/usr/bin/env python3
"""Video Cloner — Major Step 3B.4B full detected-fill rollout.

Applies a source-supported fill color to all 116 V3 Text+ captions. Direct
caption-style-event fills are preferred; cues without a matched event use the
classified caption group's estimated text color. The old low-confidence rule
that replaced bright fills with the darkest stroke component is never used.

The accepted Step 3B.3C glow/outline modes, fonts, text, layout, timing, tracks,
and all Step 3C animation targets are protected. First and idempotent reports
are archived separately. Any failed protected-integrity check rolls attempted
fill writes back to their exact pre-run values.
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

VERSION = "resolve_caption_fill_color_step_3B_4B_v1_0_full_detected_fill_rollout"
DEFAULT_PROJECT_ROOT = r"C:\Users\User\Downloads\Projects\Video Cloner"
DEFAULT_VIDEO_ID = "DZsqH7auhjt"
DEFAULT_CONFIG_NAME = "resolve_caption_fill_color_full_step_3B_4B_config.json"
V3_NAME_RE = re.compile(r"^VC_TEXTPLUS_(?P<index>\d+)_(?P<cue>sub_\d+)$", re.IGNORECASE)


def now_unix() -> float:
    return round(time.time(), 6)


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp.replace(path)


def canonical_hash(payload: Dict[str, Any]) -> str:
    clean = dict(payload)
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
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


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
        "plan_path": str(analysis / f"{video_id}_caption_fill_color_full_plan_step_3B_4B.json"),
        "latest_report_path": str(davinci / f"{video_id}_resolve_fill_color_full_step_3B_4B_report.json"),
        "first_report_path": str(davinci / f"{video_id}_resolve_fill_color_full_step_3B_4B_first_application_report.json"),
        "idempotency_report_path": str(davinci / f"{video_id}_resolve_fill_color_full_step_3B_4B_idempotency_report.json"),
        "state_path": str(davinci / f"{video_id}_resolve_fill_color_full_step_3B_4B_state.json"),
        "workspace_status_path": str(davinci / f"{video_id}_resolve_fill_color_full_step_3B_4B_workspace_status.json"),
        "workspace_log_path": str(davinci / f"{video_id}_resolve_fill_color_full_step_3B_4B_workspace.log"),
        "workspace_lock_path": str(davinci / f"{video_id}_resolve_fill_color_full_step_3B_4B_workspace.lock"),
        "expected_v3_count": 116,
        "expected_direct_event_fill_count": 66,
        "expected_group_estimated_fill_count": 50,
        "value_tolerance": 1e-6,
        "animation_value_tolerance": 1e-5,
        "save_settle_sec": 1.5,
        "rollback_on_failure": True,
        "show_completion_message": True,
    }


def config_path() -> Path:
    env = os.environ.get("VC_STEP_3B4B_CONFIG")
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
    return [{"name": name, "start": item_start(items[name]), "end": item_end(items[name])} for name in sorted(items)]


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
    if frame is None:
        value = safe_call(tool, "GetInput", input_name, default=None)
    else:
        value = safe_call(tool, "GetInput", input_name, int(frame), default=None)
    if value is not None:
        return value
    obj = find_input(tool, input_name)
    if obj is not None:
        try:
            return obj[int(frame or 0)]
        except Exception:
            pass
    return None


def write_input(tool: Any, input_name: str, expected: Any, tolerance: float) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    try:
        returned = tool.SetInput(input_name, expected)
        actual = read_input(tool, input_name)
        matched = values_match(actual, expected, tolerance)
        attempts.append({"method": "Tool.SetInput", "returned": json_safe(returned), "actual": json_safe(actual), "matched": matched})
        if matched:
            return {"ok": True, "input": input_name, "expected": expected, "actual": json_safe(actual), "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "Tool.SetInput", "error": f"{type(exc).__name__}: {exc}"})
    try:
        setattr(tool, input_name, expected)
        actual = read_input(tool, input_name)
        matched = values_match(actual, expected, tolerance)
        attempts.append({"method": "setattr", "actual": json_safe(actual), "matched": matched})
        if matched:
            return {"ok": True, "input": input_name, "expected": expected, "actual": json_safe(actual), "attempts": attempts}
    except Exception as exc:
        attempts.append({"method": "setattr", "error": f"{type(exc).__name__}: {exc}"})
    return {"ok": False, "input": input_name, "expected": expected, "actual": json_safe(read_input(tool, input_name)), "attempts": attempts}


def read_candidates(tool: Any, candidates: Sequence[str]) -> Dict[str, Any]:
    for name in candidates:
        if find_input(tool, name) is None:
            continue
        return {"resolved_input": name, "value": json_safe(read_input(tool, name))}
    return {"resolved_input": None, "value": None}


def identity_snapshot(item: Any, tool: Any) -> Dict[str, Any]:
    return {
        "name": item_name(item),
        "start": item_start(item),
        "end": item_end(item),
        "text": str(read_input(tool, "StyledText") or ""),
        "font": str(read_input(tool, "Font") or ""),
        "style": str(read_input(tool, "Style") or ""),
    }


def fill_snapshot(tool: Any) -> Dict[str, Any]:
    return {name: json_safe(read_input(tool, name)) for name in ("Enabled1", "Red1", "Green1", "Blue1", "Alpha1")}


def layout_snapshot(tool: Any) -> Dict[str, Any]:
    center_obj = find_input(tool, "Center")
    size_obj = find_input(tool, "Size")
    return {
        "center_at_local_zero": json_safe(read_input(tool, "Center", 0)),
        "center_modifier_connected": connected_output(center_obj) is not None,
        "size_modifier_connected": connected_output(size_obj) is not None,
    }


def shading_snapshot(tool: Any) -> Dict[str, Any]:
    specs = {
        "outline": {
            "Enabled2": ["Enabled2"],
            "ElementShape2": ["ElementShape2", "Appearance2"],
            "Red2": ["Red2"], "Green2": ["Green2"], "Blue2": ["Blue2"],
            "Alpha2": ["Alpha2", "Opacity2"], "Thickness2": ["Thickness2"],
            "OutsideOnly2": ["OutsideOnly2"],
        },
        "shadow": {
            "Enabled3": ["Enabled3"],
            "ElementShape3": ["ElementShape3", "Appearance3"],
            "Red3": ["Red3"], "Green3": ["Green3"], "Blue3": ["Blue3"],
            "Opacity3": ["Opacity3", "Alpha3"], "Offset3": ["Offset3"],
            "SoftnessX3": ["SoftnessX3", "Softness3"], "SoftnessY3": ["SoftnessY3"],
        },
    }
    result: Dict[str, Any] = {}
    for effect, rows in specs.items():
        result[effect] = {key: read_candidates(tool, candidates) for key, candidates in rows.items()}
    return result


def animation_snapshot(tool: Any, targets: Sequence[Dict[str, Any]], tolerance: float) -> List[Dict[str, Any]]:
    rows = []
    tolerance = max(float(tolerance), 1e-5)
    for target in targets:
        name = str(target.get("input") or "")
        frame = int(target.get("local_frame") or 0)
        expected = target.get("expected")
        obj = find_input(tool, name)
        actual = read_input(tool, name, frame)
        connected = connected_output(obj) is not None
        matched = values_match(actual, expected, tolerance)
        rows.append({
            "input": name,
            "local_frame": frame,
            "expected": json_safe(expected),
            "actual": json_safe(actual),
            "modifier_connected": connected,
            "matched": matched,
            "present": bool(connected and matched),
        })
    return rows




def parse_hex_color(value: Any) -> Tuple[float, float, float]:
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"Invalid six-digit color: {value!r}")
    try:
        return tuple(round(int(text[i:i + 2], 16) / 255.0, 8) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as exc:
        raise ValueError(f"Invalid color: {value!r}") from exc


def target_fill(plan_item: Dict[str, Any]) -> Dict[str, float]:
    fill = plan_item.get("target_fill") or {}
    if fill.get("hex"):
        red, green, blue = parse_hex_color(fill.get("hex"))
    else:
        red = float(fill.get("red"))
        green = float(fill.get("green"))
        blue = float(fill.get("blue"))
    return {
        "Enabled1": 1.0,
        "Red1": float(red),
        "Green1": float(green),
        "Blue1": float(blue),
        "Alpha1": float(fill.get("alpha", 1.0)),
    }


def fill_matches(actual: Dict[str, Any], expected: Dict[str, Any], tolerance: float) -> bool:
    return all(values_match(actual.get(name), value, tolerance) for name, value in expected.items())


def write_fill(comp: Any, tool: Any, expected: Dict[str, Any], tolerance: float) -> Dict[str, Any]:
    writes: List[Dict[str, Any]] = []
    try:
        comp.Lock()
    except Exception:
        pass
    try:
        for name in ("Enabled1", "Red1", "Green1", "Blue1", "Alpha1"):
            writes.append(write_input(tool, name, expected[name], tolerance))
    finally:
        try:
            comp.Unlock()
        except Exception:
            pass
    readback = fill_snapshot(tool)
    return {
        "ok": all(row.get("ok") for row in writes) and fill_matches(readback, expected, tolerance),
        "writes": writes,
        "readback": readback,
    }


def restore_fill(comp: Any, tool: Any, baseline: Dict[str, Any], tolerance: float) -> Dict[str, Any]:
    writes: List[Dict[str, Any]] = []
    try:
        comp.Lock()
    except Exception:
        pass
    try:
        for name in ("Enabled1", "Red1", "Green1", "Blue1", "Alpha1"):
            value = baseline.get(name)
            if value is not None:
                writes.append(write_input(tool, name, value, tolerance))
    finally:
        try:
            comp.Unlock()
        except Exception:
            pass
    readback = fill_snapshot(tool)
    return {
        "ok": all(row.get("ok") for row in writes) and snapshots_match(readback, baseline, tolerance),
        "writes": writes,
        "readback": readback,
    }


def snapshot_value(snapshot: Dict[str, Any], effect: str, key: str) -> Any:
    return (((snapshot.get(effect) or {}).get(key) or {}).get("value"))


def effect_mode_matches(snapshot: Dict[str, Any], mode: str, tolerance: float) -> bool:
    enabled2 = snapshot_value(snapshot, "outline", "Enabled2")
    enabled3 = snapshot_value(snapshot, "shadow", "Enabled3")
    if mode == "shadow_glow_only":
        offset = snapshot_value(snapshot, "shadow", "Offset3")
        return bool(values_match(enabled2, 0.0, tolerance) and values_match(enabled3, 1.0, tolerance) and values_match(offset, [0.0, 0.0], tolerance))
    if mode == "outline_and_shadow":
        return bool(values_match(enabled2, 1.0, tolerance) and values_match(enabled3, 1.0, tolerance))
    if mode == "none":
        return bool(values_match(enabled2, 0.0, tolerance) and values_match(enabled3, 0.0, tolerance))
    return False


def item_snapshot(item: Any, tool: Any, animation_targets: Sequence[Dict[str, Any]], animation_tolerance: float) -> Dict[str, Any]:
    return {
        "identity": identity_snapshot(item, tool),
        "fill": fill_snapshot(tool),
        "layout": layout_snapshot(tool),
        "style": shading_snapshot(tool),
        "animation": animation_snapshot(tool, animation_targets, animation_tolerance),
    }


def find_plan_items(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = [row for row in (plan.get("items") or []) if isinstance(row, dict)]
    if len(rows) != 116:
        raise RuntimeError(f"Expected 116 plan items, found {len(rows)}")
    return rows


def acquire_all(timeline: Any, expected_v3: int) -> Dict[str, Tuple[Any, Any, Any]]:
    v3 = scan_v3(timeline)
    if len(v3) != expected_v3:
        raise RuntimeError(f"Expected {expected_v3} V3 clips, found {len(v3)}")
    result: Dict[str, Tuple[Any, Any, Any]] = {}
    for name, item in v3.items():
        comp = fusion_comp(item)
        tool = textplus_tool(comp) if comp else None
        if tool is None:
            raise RuntimeError(f"Text+ tool not found: {name}")
        result[name] = (item, comp, tool)
    return result


def write_status(path: Path, base: Dict[str, Any], stage: str, current: int, total: int, item: Optional[str] = None) -> None:
    row = dict(base)
    row.update({
        "running": True,
        "stage": stage,
        "updated_at_unix": now_unix(),
        "progress": {
            "current": int(current), "total": int(total),
            "percent": round((100.0 * current / total), 1) if total else 0.0,
            "item": item,
        },
    })
    write_json(path, row)


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
    tolerance = float(cfg.get("value_tolerance") or 1e-6)
    animation_tolerance = max(float(cfg.get("animation_value_tolerance") or 1e-5), 1e-5)
    settle = max(float(cfg.get("save_settle_sec") or 1.5), 0.2)
    run_id = f"{int(time.time())}-{os.getpid()}"

    report: Dict[str, Any] = {
        "ok": False, "step": "Major Step 3B.4B", "workspace_version": VERSION,
        "config": str(cfg_path), "plan": str(plan_path), "latest_report": str(latest_path),
        "first_application_report": str(first_path), "idempotency_report": str(idempotency_path),
        "state": str(state_path), "failures": [], "warnings": [],
    }

    missing_preconditions: List[str] = []
    if not cfg_path.is_file():
        missing_preconditions.append("missing_prepared_config")
    if not plan_path.is_file():
        missing_preconditions.append("missing_prepared_plan")
    if missing_preconditions:
        report.update({
            "run_mode": "precondition_failed", "failures": missing_preconditions,
            "writes_attempted": False,
            "remediation": "Run run_prepare_DZsqH7auhjt_STEP_3B_4B.bat and continue only after PASS.",
        })
        latest_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(latest_path, report)
        status = {
            "ok": False, "running": False, "step": "Major Step 3B.4B", "version": VERSION,
            "run_id": run_id, "finished_at_unix": now_unix(), "return_code": 2,
            "run_mode": "precondition_failed", "report": str(latest_path),
            "failures": missing_preconditions, "writes_attempted": False,
        }
        write_json(status_path, status)
        append_log(log_path, "workspace_precondition_failed", status)
        return report

    if lock_path.exists():
        report.update({"run_mode": "already_running", "failures": ["workspace_already_running"]})
        write_json(latest_path, report)
        return report

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(lock_path, {"run_id": run_id, "started_at_unix": now_unix(), "version": VERSION})
    status_base = {
        "ok": False, "running": True, "step": "Major Step 3B.4B", "version": VERSION,
        "run_id": run_id, "started_at_unix": now_unix(),
    }
    write_status(status_path, status_base, "starting", 0, expected_v3)
    append_log(log_path, "workspace_started", status_base)

    try:
        plan = load_json(plan_path)
        if not plan.get("ok") or canonical_hash(plan) != plan.get("plan_hash"):
            raise RuntimeError("Step 3B.4B plan is invalid or hash-mismatched")
        items = find_plan_items(plan)
        plan_hash = str(plan.get("plan_hash"))
        previous_state = load_json(state_path) if state_path.is_file() else {}
        run_mode = "idempotent_second_run" if previous_state.get("ok") and previous_state.get("plan_hash") == plan_hash else "first_application"
        mode_path = idempotency_path if run_mode == "idempotent_second_run" else first_path
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

        baselines: Dict[str, Any] = {}
        targets: Dict[str, Any] = {}
        before_status: Dict[str, bool] = {}
        preflight_failures: List[str] = []
        for index, plan_item in enumerate(items, 1):
            name = str(plan_item.get("name"))
            item, _comp, tool = live[name]
            target = target_fill(plan_item)
            snap = item_snapshot(item, tool, plan_item.get("protected_animation_targets") or [], animation_tolerance)
            baselines[name] = snap
            targets[name] = target
            before_status[name] = fill_matches(snap["fill"], target, tolerance)
            identity = snap["identity"]
            if identity.get("name") != name or identity.get("start") != int(plan_item.get("start") or 0) or identity.get("end") != int(plan_item.get("end") or 0):
                preflight_failures.append(f"identity_preflight:{name}")
            if normalize_token(identity.get("text")) != normalize_token(plan_item.get("text")):
                preflight_failures.append(f"text_preflight:{name}")
            if normalize_token(identity.get("font")) != normalize_token(plan_item.get("expected_font_family")) or normalize_token(identity.get("style")) != normalize_token(plan_item.get("expected_font_face")):
                preflight_failures.append(f"font_preflight:{name}")
            if not effect_mode_matches(snap["style"], str(plan_item.get("protected_effect_mode") or ""), tolerance):
                preflight_failures.append(f"effect_mode_preflight:{name}")
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
            target = targets[name]
            if before_status[name]:
                write = {"ok": True, "write_mode": "not_required_already_correct", "readback": baselines[name]["fill"]}
                modified = False
            else:
                attempted_names.append(name)
                write = write_fill(comp, tool, target, tolerance)
                modified = bool(write.get("ok"))
                if modified:
                    modified_names.append(name)
            item_results.append({
                "name": name, "cue_id": plan_item.get("cue_id"),
                "fill_source": (plan_item.get("target_fill") or {}).get("source"),
                "target_hex": (plan_item.get("target_fill") or {}).get("hex"),
                "already_correct_before": before_status[name], "modified": modified, "write": write,
            })
            if not write.get("ok"):
                report["failures"].append(f"fill_write_failed:{name}")
                break
            if index == 1 or index % 5 == 0 or index == expected_v3:
                write_status(status_path, status_base, "apply_fill_colors", index, expected_v3, name)

        save_ok = False
        if not report["failures"]:
            returned = safe_call(manager, "SaveProject", default=False)
            save_ok = returned is not False
            time.sleep(settle)
            if not save_ok:
                report["failures"].append("project_save_failed")

        timeline_after = safe_call(project, "GetCurrentTimeline", default=None)
        live_after = acquire_all(timeline_after, expected_v3) if timeline_after is not None else {}
        persistent_failures: List[str] = []
        fill_verified = 0
        effect_verified = 0
        identity_failures = layout_failures = effect_failures = animation_failures = 0
        source_verified = {"caption_style_event.colors.fill": 0, "classified_caption_group.estimated_text_color": 0}
        if not report["failures"]:
            for index, plan_item in enumerate(items, 1):
                name = str(plan_item.get("name"))
                item_after, _comp_after, tool_after = live_after[name]
                after = item_snapshot(item_after, tool_after, plan_item.get("protected_animation_targets") or [], animation_tolerance)
                target = targets[name]
                fill_ok = fill_matches(after["fill"], target, tolerance)
                if fill_ok:
                    fill_verified += 1
                    source = str((plan_item.get("target_fill") or {}).get("source") or "")
                    if source in source_verified:
                        source_verified[source] += 1
                else:
                    persistent_failures.append(f"fill_persistence:{name}")
                before = baselines[name]
                if before["identity"] != after["identity"]:
                    identity_failures += 1
                    persistent_failures.append(f"identity_changed:{name}")
                if not snapshots_match(before["layout"], after["layout"], tolerance):
                    layout_failures += 1
                    persistent_failures.append(f"layout_changed:{name}")
                if snapshots_match(before["style"], after["style"], tolerance) and effect_mode_matches(after["style"], str(plan_item.get("protected_effect_mode") or ""), tolerance):
                    effect_verified += 1
                else:
                    effect_failures += 1
                    persistent_failures.append(f"effect_style_changed:{name}")
                if not all(row.get("present") for row in after["animation"]):
                    animation_failures += 1
                    persistent_failures.append(f"animation_changed:{name}")
                if index == 1 or index % 5 == 0 or index == expected_v3:
                    write_status(status_path, status_base, "persistent_verification", index, expected_v3, name)
            report["failures"].extend(persistent_failures)

        tracks_after = scan_tracks(timeline_after) if timeline_after is not None else {}
        track_integrity_ok = snapshots_match(tracks_after, tracks_before, tolerance)
        if not track_integrity_ok:
            report["failures"].append("timeline_track_integrity_failed")

        rollback = {"attempted": False, "ok": None}
        if report["failures"] and cfg.get("rollback_on_failure", True) and attempted_names:
            rollback["attempted"] = True
            rollback_rows = []
            current_live = acquire_all(safe_call(project, "GetCurrentTimeline", default=None), expected_v3)
            for name in attempted_names:
                _item, comp, tool = current_live[name]
                rollback_rows.append({"name": name, "result": restore_fill(comp, tool, baselines[name]["fill"], tolerance)})
            rollback_save = safe_call(manager, "SaveProject", default=False) is not False
            time.sleep(settle)
            rollback["items"] = rollback_rows
            rollback["save_ok"] = rollback_save
            rollback["ok"] = bool(rollback_save and all(row["result"].get("ok") for row in rollback_rows))

        plan_summary = plan.get("summary") or {}
        summary = {
            "v3_candidate_count": expected_v3,
            "plan_item_count": len(items),
            "direct_event_fill_count": int(plan_summary.get("direct_event_fill_count") or 0),
            "group_estimated_fill_count": int(plan_summary.get("group_estimated_fill_count") or 0),
            "mapped_count": len(live),
            "modified_count": len(modified_names),
            "already_correct_count": sum(1 for value in before_status.values() if value),
            "fill_requested_count": len(items),
            "fill_verified_count": fill_verified,
            "direct_event_fill_verified_count": source_verified["caption_style_event.colors.fill"],
            "group_estimated_fill_verified_count": source_verified["classified_caption_group.estimated_text_color"],
            "protected_effect_count": expected_v3,
            "protected_effect_verified_count": effect_verified,
            "protected_animation_target_count": sum(len(row.get("protected_animation_targets") or []) for row in items),
            "protected_animation_verified_count": sum(len(row.get("protected_animation_targets") or []) for row in items) if animation_failures == 0 else 0,
            "identity_integrity_failure_count": identity_failures,
            "layout_integrity_failure_count": layout_failures,
            "effect_integrity_failure_count": effect_failures,
            "animation_integrity_failure_count": animation_failures,
            "timeline_integrity_failure_count": 0 if track_integrity_ok else 1,
            "rollback_performed_count": 1 if rollback["attempted"] else 0,
            "failed_count": len(report["failures"]),
        }
        ok = not report["failures"]
        report.update({
            "ok": ok, "summary": summary, "items": item_results,
            "track_integrity": {"ok": track_integrity_ok, "before": tracks_before, "after": tracks_after},
            "rollback": rollback, "runtime_seconds": round(time.time() - started, 3),
        })
        write_json(latest_path, report)
        write_json(mode_path, report)
        if ok:
            write_json(state_path, {
                "ok": True, "step": "Major Step 3B.4B", "workspace_version": VERSION,
                "plan_hash": plan_hash, "last_run_mode": run_mode,
                "last_report": str(mode_path), "updated_at_unix": now_unix(),
            })

        status = {
            "ok": ok, "running": False, "step": "Major Step 3B.4B", "version": VERSION,
            "run_id": run_id, "finished_at_unix": now_unix(), "return_code": 0 if ok else 1,
            "run_mode": run_mode, "report": str(latest_path), "mode_report": str(mode_path),
            "summary": summary, "failures": report["failures"],
        }
        write_json(status_path, status)
        append_log(log_path, "workspace_finished", status)
        return report

    except StopIteration:
        report["runtime_seconds"] = round(time.time() - started, 3)
        write_json(latest_path, report)
        status = {
            "ok": False, "running": False, "step": "Major Step 3B.4B", "version": VERSION,
            "run_id": run_id, "finished_at_unix": now_unix(), "return_code": 2,
            "run_mode": report.get("run_mode"), "report": str(latest_path),
            "failures": report.get("failures") or [],
        }
        write_json(status_path, status)
        append_log(log_path, "workspace_preflight_failed", status)
        return report
    except Exception as exc:
        report.update({
            "ok": False, "run_mode": "exception", "failures": ["workspace_exception"],
            "exception": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(),
            "runtime_seconds": round(time.time() - started, 3),
        })
        write_json(latest_path, report)
        status = {
            "ok": False, "running": False, "step": "Major Step 3B.4B", "version": VERSION,
            "run_id": run_id, "finished_at_unix": now_unix(), "return_code": 1,
            "run_mode": "exception", "report": str(latest_path),
            "exception": report["exception"], "traceback": report["traceback"],
        }
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
            "Video Cloner — Step 3B.4B full fill rollout complete",
            "Full V3 source-fill rollout finished.\n\n"
            f"V3 clips: {summary.get('v3_candidate_count', 0)}\n"
            f"Direct event fills: {summary.get('direct_event_fill_count', 0)}\n"
            f"Group-estimated fills: {summary.get('group_estimated_fill_count', 0)}\n"
            f"Modified: {summary.get('modified_count', 0)}\n"
            f"Already correct: {summary.get('already_correct_count', 0)}\n"
            f"Fills verified: {summary.get('fill_verified_count', 0)}/{summary.get('fill_requested_count', 0)}\n"
            f"Effects preserved: {summary.get('protected_effect_verified_count', 0)}/{summary.get('protected_effect_count', 0)}\n"
            f"Step 3C targets preserved: {summary.get('protected_animation_verified_count', 0)}/{summary.get('protected_animation_target_count', 0)}\n"
            f"Failures: {summary.get('failed_count', 0)}\n\n"
            f"Mode report:\n{report.get('mode_report')}",
            error=False,
        )
    else:
        if report.get("run_mode") == "precondition_failed":
            message = (
                "Step 3B.4B was not prepared, so no Resolve writes were attempted.\n\nFailures:\n- "
                + "\n- ".join(report.get("failures") or ["missing preparation output"])
                + "\n\nRun run_prepare_DZsqH7auhjt_STEP_3B_4B.bat and continue only after PASS.\n\n"
                + f"Report:\n{report.get('latest_report')}"
            )
        else:
            message = (
                "The full fill-color rollout did not pass.\n\nFailures:\n- "
                + "\n- ".join(report.get("failures") or [report.get("exception") or "unknown failure"])
                + f"\n\nReport:\n{report.get('latest_report')}"
            )
        show_message("Video Cloner — Step 3B.4B full fill rollout failed", message, error=True)


_AUTORUN_DONE = False


def _workspace_autorun() -> None:
    global _AUTORUN_DONE
    if _AUTORUN_DONE:
        return
    _AUTORUN_DONE = True
    main()


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1":
    _workspace_autorun()
