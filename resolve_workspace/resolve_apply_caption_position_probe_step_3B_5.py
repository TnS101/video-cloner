#!/usr/bin/env python3
"""Video Cloner — Major Step 3B.5A source-position correction probe.

Corrects only V3 Text+ cue sub_034 ("high") from its inherited Center to the
near-time source-group center. The remaining 115 captions are read-only. All
font, text, size, fill, glow/outline, timing, track structure and the 16 Step 3C
animation targets are protected. First and idempotent reports are archived
separately. On any protected-integrity failure the original Center is restored.
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

VERSION = "resolve_caption_position_step_3B_5A_v1_0_source_position_probe"
DEFAULT_PROJECT_ROOT = r"C:\Users\User\Downloads\Projects\Video Cloner"
DEFAULT_VIDEO_ID = "DZsqH7auhjt"
DEFAULT_CONFIG_NAME = "resolve_caption_position_step_3B_5A_config.json"
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
        "plan_path": str(analysis / f"{video_id}_caption_position_probe_plan_step_3B_5A.json"),
        "latest_report_path": str(davinci / f"{video_id}_resolve_position_step_3B_5A_report.json"),
        "first_report_path": str(davinci / f"{video_id}_resolve_position_step_3B_5A_first_application_report.json"),
        "idempotency_report_path": str(davinci / f"{video_id}_resolve_position_step_3B_5A_idempotency_report.json"),
        "state_path": str(davinci / f"{video_id}_resolve_position_step_3B_5A_state.json"),
        "workspace_status_path": str(davinci / f"{video_id}_resolve_position_step_3B_5A_workspace_status.json"),
        "workspace_log_path": str(davinci / f"{video_id}_resolve_position_step_3B_5A_workspace.log"),
        "workspace_lock_path": str(davinci / f"{video_id}_resolve_position_step_3B_5A_workspace.lock"),
        "expected_v3_count": 116,
        "probe_cue_id": "sub_034",
        "value_tolerance": 1e-6,
        "animation_value_tolerance": 1e-5,
        "save_settle_sec": 1.5,
        "rollback_on_failure": True,
        "show_completion_message": True,
    }


def config_path() -> Path:
    env = os.environ.get("VC_STEP_3B5A_CONFIG")
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
    result: Dict[str, Any] = {}
    for item in track_items(timeline, "video", 3):
        name = item_name(item)
        if V3_NAME_RE.match(name):
            result[name] = item
    return result


def v3_ranges(items: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sorted(({"name": name, "start": item_start(item), "end": item_end(item)} for name, item in items.items()), key=lambda row: (row["start"], row["end"], row["name"]))


def fusion_comp(item: Any) -> Any:
    count = int(safe_call(item, "GetFusionCompCount", default=0) or 0)
    for index in range(1, count + 1):
        comp = safe_call(item, "GetFusionCompByIndex", index, default=None)
        if comp is not None:
            return comp
    comp = safe_call(item, "GetFusionCompByIndex", 1, default=None)
    if comp is not None:
        return comp
    return safe_call(item, "GetFusionCompNameList", default=None)


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


def write_point(tool: Any, input_name: str, expected: Sequence[float], tolerance: float) -> Dict[str, Any]:
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


def size_snapshot(tool: Any) -> Dict[str, Any]:
    obj = find_input(tool, "Size")
    return {"value_at_local_zero": json_safe(read_input(tool, "Size", 0)), "modifier_connected": connected_output(obj) is not None}


def shading_snapshot(tool: Any) -> Dict[str, Any]:
    specs = {
        "outline": {
            "Enabled2": ["Enabled2"], "ElementShape2": ["ElementShape2", "Appearance2"],
            "Red2": ["Red2"], "Green2": ["Green2"], "Blue2": ["Blue2"],
            "Alpha2": ["Alpha2", "Opacity2"], "Thickness2": ["Thickness2"], "OutsideOnly2": ["OutsideOnly2"],
        },
        "shadow": {
            "Enabled3": ["Enabled3"], "ElementShape3": ["ElementShape3", "Appearance3"],
            "Red3": ["Red3"], "Green3": ["Green3"], "Blue3": ["Blue3"],
            "Opacity3": ["Opacity3", "Alpha3"], "Offset3": ["Offset3"],
            "SoftnessX3": ["SoftnessX3", "Softness3"], "SoftnessY3": ["SoftnessY3"],
        },
    }
    return {effect: {key: read_candidates(tool, candidates) for key, candidates in rows.items()} for effect, rows in specs.items()}


def animation_snapshot(tool: Any, targets: Sequence[Dict[str, Any]], tolerance: float) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    tolerance = max(float(tolerance), 1e-5)
    for target in targets:
        name = str(target.get("input") or "")
        frame = int(target.get("local_frame") or 0)
        expected = target.get("expected")
        obj = find_input(tool, name)
        actual = read_input(tool, name, frame)
        connected = connected_output(obj) is not None
        matched = values_match(actual, expected, tolerance)
        rows.append({"input": name, "local_frame": frame, "expected": json_safe(expected), "actual": json_safe(actual), "modifier_connected": connected, "matched": matched, "present": bool(connected and matched)})
    return rows


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


def all_animation_snapshot(acquired: Dict[str, Tuple[Any, Any, Any]], plan_items: Sequence[Dict[str, Any]], tolerance: float) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    by_name = {str(item.get("name")): item for item in plan_items}
    for name, (_, _, tool) in acquired.items():
        plan_item = by_name.get(name) or {}
        for target in animation_snapshot(tool, plan_item.get("protected_animation_targets") or [], tolerance):
            target["name"] = name
            target["cue_id"] = plan_item.get("cue_id")
            rows.append(target)
    rows.sort(key=lambda row: (row.get("name"), row.get("input"), row.get("local_frame")))
    return rows


def select_probe(plan: Dict[str, Any], cue_id: str) -> Dict[str, Any]:
    matches = [row for row in (plan.get("items") or []) if isinstance(row, dict) and row.get("selected_probe") and str(row.get("cue_id")) == cue_id]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one selected probe {cue_id}, found {len(matches)}")
    return matches[0]


def write_status(path: Path, base: Dict[str, Any], stage: str) -> None:
    payload = dict(base)
    payload.update({"stage": stage, "updated_at_unix": now_unix()})
    write_json(path, payload)


def run() -> Dict[str, Any]:
    started = time.time()
    config_file, cfg = load_config()
    plan_path = Path(cfg["plan_path"])
    latest_path = Path(cfg["latest_report_path"])
    first_path = Path(cfg["first_report_path"])
    idempotency_path = Path(cfg["idempotency_report_path"])
    state_path = Path(cfg["state_path"])
    status_path = Path(cfg["workspace_status_path"])
    log_path = Path(cfg["workspace_log_path"])
    lock_path = Path(cfg["workspace_lock_path"])
    expected_v3 = int(cfg.get("expected_v3_count", 116))
    cue_id = str(cfg.get("probe_cue_id", "sub_034"))
    tolerance = max(float(cfg.get("value_tolerance", 1e-6)), 1e-6)
    animation_tolerance = max(float(cfg.get("animation_value_tolerance", 1e-5)), 1e-5)
    settle = max(float(cfg.get("save_settle_sec", 1.5)), 0.1)
    run_id = f"{int(time.time())}-{os.getpid()}"

    report: Dict[str, Any] = {
        "ok": False,
        "step": "Major Step 3B.5A",
        "workspace_version": VERSION,
        "config": str(config_file),
        "plan": str(plan_path),
        "latest_report": str(latest_path),
        "first_application_report": str(first_path),
        "idempotency_report": str(idempotency_path),
        "state": str(state_path),
        "probe_cue_id": cue_id,
        "failures": [],
        "warnings": [],
    }

    if lock_path.exists():
        report.update({"run_mode": "already_running", "failures": ["workspace_already_running"]})
        write_json(latest_path, report)
        return report
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps({"run_id": run_id, "started_at_unix": now_unix(), "version": VERSION}), encoding="utf-8")
    status_base = {"ok": False, "running": True, "step": "Major Step 3B.5A", "version": VERSION, "run_id": run_id, "started_at_unix": now_unix(), "report": str(latest_path)}
    write_status(status_path, status_base, "starting")
    append_log(log_path, "workspace_started", status_base)

    try:
        if not plan_path.is_file():
            report.update({"run_mode": "preflight_failed", "failures": ["plan_missing"], "preflight": {"writes_attempted": False, "rollback_required": False}})
            raise StopIteration
        plan = load_json(plan_path)
        if not plan.get("ok") or plan.get("plan_hash") != canonical_hash(plan):
            report.update({"run_mode": "preflight_failed", "failures": ["plan_invalid"], "preflight": {"writes_attempted": False, "rollback_required": False}})
            raise StopIteration
        probe = select_probe(plan, cue_id)
        target = normalize_point(probe.get("target_center"))
        if target is None:
            raise RuntimeError("Probe target Center is invalid")
        if probe.get("protected_animation_targets"):
            report.update({"run_mode": "preflight_failed", "failures": ["probe_center_is_animated"], "preflight": {"writes_attempted": False, "rollback_required": False}})
            raise StopIteration

        resolve_app = get_resolve()
        manager = safe_call(resolve_app, "GetProjectManager", default=None)
        project = safe_call(manager, "GetCurrentProject", default=None)
        timeline = safe_call(project, "GetCurrentTimeline", default=None)
        if manager is None or project is None or timeline is None:
            raise RuntimeError("Current Resolve project/timeline unavailable")

        write_status(status_path, status_base, "preflight")
        acquired_before = acquire_all(timeline, expected_v3)
        if probe["name"] not in acquired_before:
            raise RuntimeError(f"Probe item not found: {probe['name']}")
        probe_item, probe_comp, probe_tool = acquired_before[probe["name"]]
        identity_before = identity_snapshot(probe_item, probe_tool)
        expected_identity = {
            "name": probe["name"], "start": int(probe["start"]), "end": int(probe["end"]),
            "text": probe["text"], "font": probe["expected_font_family"], "style": probe["expected_font_face"],
        }
        identity_ok = all(values_match(identity_before.get(key), value, tolerance) for key, value in expected_identity.items())
        center_obj = find_input(probe_tool, "Center")
        center_connected = connected_output(center_obj) is not None
        if not identity_ok:
            report.update({"run_mode": "preflight_failed", "failures": ["probe_identity_preflight_failed"], "preflight": {"writes_attempted": False, "rollback_required": False, "identity": identity_before, "expected_identity": expected_identity}})
            raise StopIteration
        if center_connected:
            report.update({"run_mode": "preflight_failed", "failures": ["probe_center_modifier_unexpected"], "preflight": {"writes_attempted": False, "rollback_required": False, "center_modifier_connected": True}})
            raise StopIteration

        tracks_before = scan_tracks(timeline)
        ranges_before = v3_ranges({name: row[0] for name, row in acquired_before.items()})
        animation_before = all_animation_snapshot(acquired_before, plan.get("items") or [], animation_tolerance)
        if len(animation_before) != 16 or not all(row.get("present") for row in animation_before):
            report.update({"run_mode": "preflight_failed", "failures": ["step_3C_animation_preflight_failed"], "preflight": {"writes_attempted": False, "rollback_required": False, "animation": animation_before}})
            raise StopIteration

        baseline = {
            "identity": identity_before,
            "center": json_safe(read_input(probe_tool, "Center")),
            "center_modifier_connected": center_connected,
            "size": size_snapshot(probe_tool),
            "fill": fill_snapshot(probe_tool),
            "shading": shading_snapshot(probe_tool),
            "animation": animation_before,
        }
        state = load_json(state_path) if state_path.is_file() else {}
        state_valid = bool(state.get("ok") and state.get("plan_hash") == plan.get("plan_hash") and state.get("probe_cue_id") == cue_id)
        run_mode = "idempotent_second_run" if state_valid else "first_application"
        already_correct = values_match(baseline["center"], target, tolerance)
        write_result = {"ok": True, "write_mode": "not_required_already_correct", "expected": target, "actual": baseline["center"], "attempts": []}
        modified = False
        if not already_correct:
            safe_call(probe_comp, "Lock", default=None)
            try:
                write_result = write_point(probe_tool, "Center", target, tolerance)
            finally:
                safe_call(probe_comp, "Unlock", default=None)
            modified = bool(write_result.get("ok"))

        write_status(status_path, status_base, "save_after_write")
        save = {"attempted": True, "ok": False}
        try:
            returned = manager.SaveProject()
            save.update({"ok": returned is not False, "returned": json_safe(returned)})
        except Exception as exc:
            save["error"] = f"{type(exc).__name__}: {exc}"
        time.sleep(settle)

        acquired_after = acquire_all(timeline, expected_v3)
        probe_item_after, probe_comp_after, probe_tool_after = acquired_after[probe["name"]]
        identity_after = identity_snapshot(probe_item_after, probe_tool_after)
        center_after = json_safe(read_input(probe_tool_after, "Center"))
        size_after = size_snapshot(probe_tool_after)
        fill_after = fill_snapshot(probe_tool_after)
        shading_after = shading_snapshot(probe_tool_after)
        animation_after = all_animation_snapshot(acquired_after, plan.get("items") or [], animation_tolerance)
        tracks_after = scan_tracks(timeline)
        ranges_after = v3_ranges({name: row[0] for name, row in acquired_after.items()})

        failures: List[str] = []
        if not write_result.get("ok"):
            failures.append("center_write_failed")
        if not save.get("ok"):
            failures.append("project_save_failed")
        if not values_match(center_after, target, tolerance):
            failures.append("center_persistent_readback_failed")
        if not snapshots_match(identity_after, baseline["identity"], tolerance):
            failures.append("caption_identity_changed")
        if not snapshots_match(size_after, baseline["size"], tolerance):
            failures.append("caption_size_changed")
        if not snapshots_match(fill_after, baseline["fill"], tolerance):
            failures.append("caption_fill_changed")
        if not snapshots_match(shading_after, baseline["shading"], tolerance):
            failures.append("caption_effects_changed")
        if len(animation_after) != 16 or not all(row.get("present") for row in animation_after):
            failures.append("step_3C_animation_changed")
        if not snapshots_match(animation_after, baseline["animation"], animation_tolerance):
            failures.append("step_3C_animation_snapshot_changed")
        if tracks_before != tracks_after:
            failures.append("timeline_track_integrity_failed")
        if ranges_before != ranges_after:
            failures.append("v3_track_integrity_failed")

        rollback = {"attempted": False, "ok": None}
        if failures and cfg.get("rollback_on_failure", True):
            rollback["attempted"] = True
            baseline_point = normalize_point(baseline["center"])
            if baseline_point is None:
                rollback["ok"] = False
                rollback["error"] = "baseline_center_invalid"
            else:
                safe_call(probe_comp_after, "Lock", default=None)
                try:
                    rollback_write = write_point(probe_tool_after, "Center", baseline_point, tolerance)
                finally:
                    safe_call(probe_comp_after, "Unlock", default=None)
                try:
                    returned = manager.SaveProject()
                    rollback_save = returned is not False
                except Exception:
                    rollback_save = False
                time.sleep(settle)
                acquired_rollback = acquire_all(timeline, expected_v3)
                rollback_center = json_safe(read_input(acquired_rollback[probe["name"]][2], "Center"))
                rollback.update({"write": rollback_write, "save_ok": rollback_save, "persistent_center": rollback_center, "ok": bool(rollback_write.get("ok") and rollback_save and values_match(rollback_center, baseline_point, tolerance))})

        ok = not failures
        summary = {
            "v3_candidate_count": len(acquired_after),
            "plan_item_count": len(plan.get("items") or []),
            "probe_item_count": 1,
            "mapped_count": 1,
            "modified_count": 1 if (modified and not already_correct) else 0,
            "already_correct_count": 1 if already_correct else 0,
            "position_requested_count": 1,
            "position_verified_count": 1 if values_match(center_after, target, tolerance) else 0,
            "protected_fill_verified_count": 1 if "caption_fill_changed" not in failures else 0,
            "protected_effect_verified_count": 1 if "caption_effects_changed" not in failures else 0,
            "protected_size_verified_count": 1 if "caption_size_changed" not in failures else 0,
            "protected_animation_target_count": len(animation_after),
            "protected_animation_verified_count": sum(1 for row in animation_after if row.get("present")),
            "identity_integrity_failure_count": 1 if "caption_identity_changed" in failures else 0,
            "style_integrity_failure_count": sum(1 for value in ("caption_size_changed", "caption_fill_changed", "caption_effects_changed") if value in failures),
            "animation_integrity_failure_count": sum(1 for value in ("step_3C_animation_changed", "step_3C_animation_snapshot_changed") if value in failures),
            "timeline_integrity_failure_count": sum(1 for value in ("timeline_track_integrity_failed", "v3_track_integrity_failed") if value in failures),
            "rollback_performed_count": 1 if rollback["attempted"] else 0,
            "failed_count": 0 if ok else 1,
        }
        mode_path = first_path if run_mode == "first_application" else idempotency_path
        report.update({
            "ok": ok,
            "run_mode": run_mode,
            "mode_report": str(mode_path),
            "plan_hash": plan.get("plan_hash"),
            "project_name": safe_call(project, "GetName", default=None),
            "timeline_name": safe_call(timeline, "GetName", default=None),
            "probe_name": probe.get("name"),
            "probe_text": probe.get("text"),
            "source_position": probe.get("source_position"),
            "previous_reported_center": probe.get("previous_reported_center"),
            "target_center": target,
            "summary": summary,
            "before": baseline,
            "write": write_result,
            "save_after_write": save,
            "after": {"identity": identity_after, "center": center_after, "size": size_after, "fill": fill_after, "shading": shading_after, "animation": animation_after},
            "track_integrity": {"ok": tracks_before == tracks_after, "before": tracks_before, "after": tracks_after},
            "v3_track_integrity": {"ok": ranges_before == ranges_after, "before": ranges_before, "after": ranges_after},
            "rollback": rollback,
            "failures": failures,
            "runtime_seconds": round(time.time() - started, 3),
        })
        write_json(latest_path, report)
        write_json(mode_path, report)
        if ok:
            write_json(state_path, {
                "ok": True,
                "step": "Major Step 3B.5A",
                "workspace_version": VERSION,
                "plan_hash": plan.get("plan_hash"),
                "probe_cue_id": cue_id,
                "target_center": target,
                "original_center": baseline.get("center"),
                "last_run_mode": run_mode,
                "last_report": str(mode_path),
                "updated_at_unix": now_unix(),
            })

        status = {"ok": ok, "running": False, "step": "Major Step 3B.5A", "version": VERSION, "run_id": run_id, "finished_at_unix": now_unix(), "return_code": 0 if ok else 1, "run_mode": run_mode, "report": str(latest_path), "mode_report": str(mode_path), "summary": summary, "failures": failures}
        write_json(status_path, status)
        append_log(log_path, "workspace_finished", status)
        return report

    except StopIteration:
        report["runtime_seconds"] = round(time.time() - started, 3)
        write_json(latest_path, report)
        status = {"ok": False, "running": False, "step": "Major Step 3B.5A", "version": VERSION, "run_id": run_id, "finished_at_unix": now_unix(), "return_code": 2, "run_mode": report.get("run_mode"), "report": str(latest_path), "failures": report.get("failures") or []}
        write_json(status_path, status)
        append_log(log_path, "workspace_preflight_failed", status)
        return report
    except Exception as exc:
        report.update({"ok": False, "run_mode": "exception", "failures": ["workspace_exception"], "exception": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(), "runtime_seconds": round(time.time() - started, 3)})
        write_json(latest_path, report)
        status = {"ok": False, "running": False, "step": "Major Step 3B.5A", "version": VERSION, "run_id": run_id, "finished_at_unix": now_unix(), "return_code": 1, "run_mode": "exception", "report": str(latest_path), "exception": report["exception"], "traceback": report["traceback"]}
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
            "Video Cloner — Step 3B.5A position probe complete",
            "Source-position correction probe finished.\n\n"
            f"Probe: {report.get('probe_cue_id')} / {report.get('probe_text')}\n"
            f"Target Center: {report.get('target_center')}\n"
            f"Modified: {summary.get('modified_count', 0)}\n"
            f"Already correct: {summary.get('already_correct_count', 0)}\n"
            f"Position verified: {summary.get('position_verified_count', 0)}/1\n"
            f"Fill preserved: {summary.get('protected_fill_verified_count', 0)}/1\n"
            f"Effects preserved: {summary.get('protected_effect_verified_count', 0)}/1\n"
            f"Step 3C targets preserved: {summary.get('protected_animation_verified_count', 0)}/{summary.get('protected_animation_target_count', 0)}\n"
            f"Failures: {summary.get('failed_count', 0)}\n\n"
            f"Mode report:\n{report.get('mode_report')}",
            error=False,
        )
    else:
        show_message(
            "Video Cloner — Step 3B.5A position probe failed",
            "The source-position probe did not pass.\n\nFailures:\n- "
            + "\n- ".join(report.get("failures") or [report.get("exception") or "unknown failure"])
            + f"\n\nReport:\n{report.get('latest_report')}",
            error=True,
        )


_AUTORUN_DONE = False


def _workspace_autorun() -> None:
    global _AUTORUN_DONE
    if _AUTORUN_DONE:
        return
    _AUTORUN_DONE = True
    main()


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1":
    _workspace_autorun()
