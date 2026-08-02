#!/usr/bin/env python3
"""Video Cloner — Major Step 3B.4A detected-fill correction probe.

This Resolve Workspace script corrects only the V3 Text+ fill color of sub_019
("closing") from the known bad low-confidence dark-fill fallback to the source
style-event fill (#f9f7f9). It preserves the verified Step 3B.3B outline/shadow,
font, text, position, timing, tracks and both Step 3C Size keyframes. First and
idempotent reports are archived separately. Any failed protected-integrity check
rolls the fill back to its exact pre-run baseline.
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

VERSION = "resolve_caption_fill_color_step_3B_4A_v1_0_detected_fill_probe"
DEFAULT_PROJECT_ROOT = r"C:\Users\User\Downloads\Projects\Video Cloner"
DEFAULT_VIDEO_ID = "DZsqH7auhjt"
DEFAULT_CONFIG_NAME = "resolve_caption_fill_color_step_3B_4A_config.json"
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
        "plan_path": str(analysis / f"{video_id}_caption_fill_color_probe_plan_step_3B_4A.json"),
        "latest_report_path": str(davinci / f"{video_id}_resolve_fill_color_step_3B_4A_report.json"),
        "first_report_path": str(davinci / f"{video_id}_resolve_fill_color_step_3B_4A_first_application_report.json"),
        "idempotency_report_path": str(davinci / f"{video_id}_resolve_fill_color_step_3B_4A_idempotency_report.json"),
        "state_path": str(davinci / f"{video_id}_resolve_fill_color_step_3B_4A_state.json"),
        "workspace_status_path": str(davinci / f"{video_id}_resolve_fill_color_step_3B_4A_workspace_status.json"),
        "workspace_log_path": str(davinci / f"{video_id}_resolve_fill_color_step_3B_4A_workspace.log"),
        "workspace_lock_path": str(davinci / f"{video_id}_resolve_fill_color_step_3B_4A_workspace.lock"),
        "expected_v3_count": 116,
        "probe_cue_id": "sub_019",
        "value_tolerance": 1e-6,
        "animation_value_tolerance": 1e-5,
        "save_settle_sec": 1.5,
        "rollback_on_failure": True,
        "show_completion_message": True,
    }


def config_path() -> Path:
    env = os.environ.get("VC_STEP_3B4A_CONFIG")
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


def target_fill(item: Dict[str, Any]) -> Dict[str, float]:
    source = item.get("source_fill") or {}
    return {
        "Enabled1": 1.0,
        "Red1": float(source.get("red")),
        "Green1": float(source.get("green")),
        "Blue1": float(source.get("blue")),
        "Alpha1": float(source.get("alpha", 1.0)),
    }


def fill_matches(actual: Dict[str, Any], expected: Dict[str, Any], tolerance: float) -> bool:
    return all(values_match(actual.get(key), value, tolerance) for key, value in expected.items())


def write_fill(comp: Any, tool: Any, expected: Dict[str, Any], tolerance: float) -> Dict[str, Any]:
    try:
        comp.Lock()
    except Exception:
        pass
    writes = []
    try:
        for key in ("Enabled1", "Red1", "Green1", "Blue1", "Alpha1"):
            writes.append(write_input(tool, key, expected[key], tolerance))
    finally:
        try:
            comp.Unlock()
        except Exception:
            pass
    readback = fill_snapshot(tool)
    return {"ok": all(row.get("ok") for row in writes) and fill_matches(readback, expected, tolerance), "writes": writes, "readback": readback}


def protected_snapshot(item: Any, tool: Any, targets: Sequence[Dict[str, Any]], animation_tolerance: float) -> Dict[str, Any]:
    return {
        "identity": identity_snapshot(item, tool),
        "fill": fill_snapshot(tool),
        "layout": layout_snapshot(tool),
        "shading": shading_snapshot(tool),
        "animation": animation_snapshot(tool, targets, animation_tolerance),
    }


def protected_integrity(before: Dict[str, Any], after: Dict[str, Any], target: Dict[str, Any], tolerance: float) -> Dict[str, Any]:
    failures: List[str] = []
    if before.get("identity") != after.get("identity"):
        failures.append("caption_identity_changed")
    if not snapshots_match(after.get("layout"), before.get("layout"), tolerance):
        failures.append("caption_layout_changed")
    if not snapshots_match(after.get("shading"), before.get("shading"), tolerance):
        failures.append("outline_shadow_changed")
    if not fill_matches(after.get("fill") or {}, target, tolerance):
        failures.append("target_fill_not_persistent")
    animation = after.get("animation") or []
    if len(animation) != len(before.get("animation") or []):
        failures.append("animation_target_count_changed")
    elif not all(row.get("present") for row in animation):
        failures.append("step_3C_animation_changed")
    return {"ok": not failures, "failures": failures, "before": before, "after": after}


def acquire_probe(timeline: Any, expected_v3: int, plan_item: Dict[str, Any]) -> Tuple[Dict[str, Any], Any, Any, Any]:
    v3 = scan_v3(timeline)
    if len(v3) != expected_v3:
        raise RuntimeError(f"Expected {expected_v3} V3 clips, found {len(v3)}")
    item = v3.get(str(plan_item.get("name")))
    if item is None:
        raise RuntimeError(f"Probe V3 item not found: {plan_item.get('name')}")
    comp = fusion_comp(item)
    tool = textplus_tool(comp) if comp else None
    if tool is None:
        raise RuntimeError("Probe Text+ tool not found")
    return v3, item, comp, tool


def select_probe(plan: Dict[str, Any], cue_id: str) -> Dict[str, Any]:
    rows = [row for row in (plan.get("items") or []) if isinstance(row, dict) and row.get("probe_selected")]
    if len(rows) != 1 or rows[0].get("cue_id") != cue_id:
        raise RuntimeError("Step 3B.4A plan does not contain the expected single probe")
    return rows[0]


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
    cue_id = str(cfg.get("probe_cue_id") or "sub_019")
    tolerance = float(cfg.get("value_tolerance") or 1e-6)
    animation_tolerance = max(float(cfg.get("animation_value_tolerance") or 1e-5), 1e-5)
    settle = float(cfg.get("save_settle_sec") or 1.5)
    run_id = f"{int(time.time())}-{os.getpid()}"

    report: Dict[str, Any] = {
        "ok": False,
        "step": "Major Step 3B.4A",
        "workspace_version": VERSION,
        "config": str(cfg_path),
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
        report.update({"run_mode": "duplicate_launch_rejected", "failures": ["workspace_lock_exists"], "runtime_seconds": 0.0})
        write_json(latest_path, report)
        return report
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps({"run_id": run_id, "started_at_unix": now_unix()}), encoding="utf-8")
    status = {"ok": False, "running": True, "step": "Major Step 3B.4A", "version": VERSION, "run_id": run_id, "started_at_unix": now_unix()}
    write_json(status_path, status)
    append_log(log_path, "workspace_started", status)

    try:
        plan = load_json(plan_path)
        if not plan.get("ok") or plan.get("plan_hash") != canonical_hash(plan):
            raise RuntimeError("Step 3B.4A plan is invalid")
        probe = select_probe(plan, cue_id)
        target = target_fill(probe)
        targets = probe.get("protected_animation_targets") or []
        if len(targets) != 2:
            raise RuntimeError("Probe must protect exactly two Step 3C targets")

        resolve_app = get_resolve()
        manager = resolve_app.GetProjectManager()
        project = manager.GetCurrentProject() if manager else None
        if project is None:
            raise RuntimeError("No Resolve project is open")
        timeline = project.GetCurrentTimeline()
        if timeline is None:
            raise RuntimeError("No Resolve timeline is open")

        tracks_before = scan_tracks(timeline)
        v3_before, item, comp, tool = acquire_probe(timeline, expected_v3, probe)
        ranges_before = v3_ranges(v3_before)
        identity = identity_snapshot(item, tool)
        expected_identity = {
            "name": probe.get("name"), "start": int(probe.get("start") or 0), "end": int(probe.get("end") or 0),
            "text": str(probe.get("text") or ""), "font": str(probe.get("expected_font_family") or ""), "style": str(probe.get("expected_font_face") or ""),
        }
        identity_checks = {
            "name": identity["name"] == expected_identity["name"],
            "start": identity["start"] == expected_identity["start"],
            "end": identity["end"] == expected_identity["end"],
            "text": normalize_text(identity["text"]) == normalize_text(expected_identity["text"]),
            "font": normalize_token(identity["font"]) == normalize_token(expected_identity["font"]),
            "style": normalize_token(identity["style"] or "Regular") == normalize_token(expected_identity["style"] or "Regular"),
        }
        if not all(identity_checks.values()):
            raise RuntimeError(f"Probe identity preflight failed: {identity_checks}")

        before = protected_snapshot(item, tool, targets, animation_tolerance)
        if not all(row.get("present") for row in before["animation"]):
            report.update({
                "run_mode": "preflight_failed", "failures": ["step_3C_animation_preflight_failed"],
                "preflight": {"writes_attempted": False, "rollback_required": False, "animation": before["animation"]},
            })
            raise StopIteration
        if not values_match((before["shading"]["outline"]["Enabled2"] or {}).get("value"), 1, tolerance) or not values_match((before["shading"]["shadow"]["Enabled3"] or {}).get("value"), 1, tolerance):
            report.update({"run_mode": "preflight_failed", "failures": ["step_3B_3B_outline_shadow_preflight_failed"], "preflight": {"writes_attempted": False, "rollback_required": False, "shading": before["shading"]}})
            raise StopIteration

        state = load_json(state_path) if state_path.is_file() else {}
        state_valid = bool(state.get("ok") and state.get("plan_hash") == plan.get("plan_hash") and state.get("probe_cue_id") == cue_id)
        run_mode = "idempotent_second_run" if state_valid else "first_application"
        already_correct = fill_matches(before["fill"], target, tolerance)
        write_result = {"ok": True, "writes": [], "readback": before["fill"], "write_mode": "not_required_already_correct"}
        modified = False
        if not already_correct:
            write_result = write_fill(comp, tool, target, tolerance)
            modified = bool(write_result.get("ok"))

        save = {"attempted": True, "ok": False}
        try:
            returned = manager.SaveProject()
            save.update({"ok": returned is not False, "returned": json_safe(returned)})
        except Exception as exc:
            save["error"] = f"{type(exc).__name__}: {exc}"
        time.sleep(settle)

        v3_after, item_after, comp_after, tool_after = acquire_probe(timeline, expected_v3, probe)
        after = protected_snapshot(item_after, tool_after, targets, animation_tolerance)
        integrity = protected_integrity(before, after, target, tolerance)
        tracks_after = scan_tracks(timeline)
        ranges_after = v3_ranges(v3_after)
        track_integrity = {"ok": tracks_before == tracks_after, "before": tracks_before, "after": tracks_after}
        v3_integrity = {"ok": ranges_before == ranges_after, "before": ranges_before, "after": ranges_after}
        persistent_ok = bool(fill_matches(after["fill"], target, tolerance))

        failures: List[str] = []
        if not write_result.get("ok"):
            failures.append("fill_write_failed")
        if not save.get("ok"):
            failures.append("project_save_failed")
        if not persistent_ok:
            failures.append("fill_persistent_readback_failed")
        failures.extend(integrity.get("failures") or [])
        if not track_integrity["ok"]:
            failures.append("timeline_track_integrity_failed")
        if not v3_integrity["ok"]:
            failures.append("v3_track_integrity_failed")

        rollback = {"attempted": False, "ok": None}
        if failures and cfg.get("rollback_on_failure", True):
            rollback["attempted"] = True
            rollback_write = write_fill(comp_after, tool_after, before["fill"], tolerance)
            try:
                returned = manager.SaveProject()
                rollback_save = returned is not False
            except Exception:
                rollback_save = False
            time.sleep(settle)
            _, rollback_item, _, rollback_tool = acquire_probe(timeline, expected_v3, probe)
            rollback_fill = fill_snapshot(rollback_tool)
            rollback["write"] = rollback_write
            rollback["save_ok"] = rollback_save
            rollback["persistent_fill"] = rollback_fill
            rollback["ok"] = bool(rollback_write.get("ok") and rollback_save and snapshots_match(rollback_fill, before["fill"], tolerance))

        ok = not failures
        summary = {
            "v3_candidate_count": len(v3_after),
            "probe_item_count": 1,
            "mapped_count": 1,
            "modified_count": 1 if (modified and not already_correct) else 0,
            "already_correct_count": 1 if already_correct else 0,
            "fill_requested_count": 1,
            "fill_verified_count": 1 if persistent_ok else 0,
            "protected_outline_shadow_count": 2,
            "protected_outline_shadow_verified_count": 2 if not any(x == "outline_shadow_changed" for x in failures) else 0,
            "protected_animation_target_count": len(targets),
            "protected_animation_verified_count": sum(1 for row in after["animation"] if row.get("present")),
            "identity_integrity_failure_count": 1 if "caption_identity_changed" in failures else 0,
            "layout_integrity_failure_count": 1 if "caption_layout_changed" in failures else 0,
            "outline_shadow_integrity_failure_count": 1 if "outline_shadow_changed" in failures else 0,
            "animation_integrity_failure_count": 1 if "step_3C_animation_changed" in failures else 0,
            "timeline_integrity_failure_count": sum(1 for x in failures if x in ("timeline_track_integrity_failed", "v3_track_integrity_failed")),
            "rollback_performed_count": 1 if rollback["attempted"] else 0,
            "failed_count": 0 if ok else 1,
        }
        mode_path = first_path if run_mode == "first_application" else idempotency_path
        report.update({
            "ok": ok, "run_mode": run_mode, "mode_report": str(mode_path), "plan_hash": plan.get("plan_hash"),
            "project_name": safe_call(project, "GetName", default=None), "timeline_name": safe_call(timeline, "GetName", default=None),
            "target_fill": probe.get("source_fill"), "identity_preflight": identity_checks, "summary": summary,
            "before": before, "write": write_result, "save_after_write": save, "after": after,
            "persistent_readback_ok": persistent_ok, "protected_integrity": integrity,
            "track_integrity": track_integrity, "v3_track_integrity": v3_integrity,
            "rollback": rollback, "failures": failures, "runtime_seconds": round(time.time() - started, 3),
        })
        write_json(latest_path, report)
        write_json(mode_path, report)
        if ok:
            write_json(state_path, {
                "ok": True, "step": "Major Step 3B.4A", "workspace_version": VERSION,
                "plan_hash": plan.get("plan_hash"), "probe_cue_id": cue_id,
                "target_fill": probe.get("source_fill"), "original_fill": before.get("fill"),
                "last_run_mode": run_mode, "last_report": str(mode_path), "updated_at_unix": now_unix(),
            })

        status = {"ok": ok, "running": False, "step": "Major Step 3B.4A", "version": VERSION, "run_id": run_id, "finished_at_unix": now_unix(), "return_code": 0 if ok else 1, "run_mode": run_mode, "report": str(latest_path), "mode_report": str(mode_path), "summary": summary, "failures": failures}
        write_json(status_path, status)
        append_log(log_path, "workspace_finished", status)
        return report

    except StopIteration:
        report["runtime_seconds"] = round(time.time() - started, 3)
        write_json(latest_path, report)
        status = {"ok": False, "running": False, "step": "Major Step 3B.4A", "version": VERSION, "run_id": run_id, "finished_at_unix": now_unix(), "return_code": 2, "run_mode": report.get("run_mode"), "report": str(latest_path), "failures": report.get("failures") or []}
        write_json(status_path, status)
        append_log(log_path, "workspace_preflight_failed", status)
        return report
    except Exception as exc:
        report.update({"ok": False, "run_mode": "exception", "failures": ["workspace_exception"], "exception": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(), "runtime_seconds": round(time.time() - started, 3)})
        write_json(latest_path, report)
        status = {"ok": False, "running": False, "step": "Major Step 3B.4A", "version": VERSION, "run_id": run_id, "finished_at_unix": now_unix(), "return_code": 1, "run_mode": "exception", "report": str(latest_path), "exception": report["exception"], "traceback": report["traceback"]}
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
        target = report.get("target_fill") or {}
        show_message(
            "Video Cloner — Step 3B.4A fill probe complete",
            "Detected-fill correction probe finished.\n\n"
            f"Probe: {report.get('probe_cue_id')} / closing\n"
            f"Target fill: {target.get('hex')}\n"
            f"Modified: {summary.get('modified_count', 0)}\n"
            f"Already correct: {summary.get('already_correct_count', 0)}\n"
            f"Fill verified: {summary.get('fill_verified_count', 0)}/1\n"
            f"Outline/shadow preserved: {summary.get('protected_outline_shadow_verified_count', 0)}/2\n"
            f"Step 3C targets preserved: {summary.get('protected_animation_verified_count', 0)}/{summary.get('protected_animation_target_count', 0)}\n"
            f"Failures: {summary.get('failed_count', 0)}\n\n"
            f"Mode report:\n{report.get('mode_report')}",
            error=False,
        )
    else:
        show_message(
            "Video Cloner — Step 3B.4A fill probe failed",
            "The fill-color probe did not pass.\n\nFailures:\n- "
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
