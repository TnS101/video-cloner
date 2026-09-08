#!/usr/bin/env python3
"""Apply Major Step 3B.6D contained source geometry rollout in Resolve."""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

VERSION = "resolve_apply_caption_source_geometry_contained_rollout_step_3B_6D_v1_1_center_size_only"
DEFAULT_PROJECT_ROOT = r"C:\Users\User\Downloads\Projects\Video Cloner"
DEFAULT_VIDEO_ID = "DZsqH7auhjt"
DEFAULT_CONFIG_NAME = "resolve_caption_source_geometry_contained_step_3B_6D_config.json"
EXPECTED_SCHEMA = "video_cloner_caption_source_geometry_contained_rollout_plan"
ALLOWED_OPERATION_PROPERTIES = {"Center", "Size"}
EXPECTED_TARGET_IDENTITY = {
    "sub_007": ("While", 196, 199),
    "sub_013": ("out", 224, 230),
    "sub_110": ("looks", 862, 868),
    "sub_114": ("AND", 888, 894),
}


def now_unix() -> float:
    return time.time()


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


def canonical_hash(value: Dict[str, Any], ignored: Sequence[str] = ()) -> str:
    clean = dict(value)
    clean.pop("plan_hash", None)
    for key in ignored:
        clean.pop(key, None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def operation_input(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    nested = row.get("target")
    return str((nested.get("input") if isinstance(nested, dict) else row.get("input")) or "")


def manifest_operations(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if not isinstance(value, dict):
        return []
    if operation_input(value):
        return [value]
    rows: List[Dict[str, Any]] = []
    for key in ("operations", "targets", "writes"):
        rows.extend(manifest_operations(value.get(key)))
    return rows


def integer(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def executable_plan_failures(plan: Dict[str, Any]) -> List[str]:
    items = list(plan.get("rollout_items") or [])
    summary = plan.get("summary") or {}
    safety = plan.get("safety_contract") or {}
    contract = plan.get("property_contract") or {}
    cue_ids = [str(row.get("cue_id") or "") for row in items]
    targets = [target for row in items for target in (row.get("targets") or [])]
    manifest = manifest_operations(plan.get("mutation_manifest"))
    properties = {operation_input(row) for row in targets + manifest}
    properties.discard("")
    center_count = sum(1 for row in targets if operation_input(row) == "Center")
    size_count = sum(1 for row in targets if operation_input(row) == "Size")
    checks = {
        "rollout_item_contract_failed": len(items) == 4 and len(cue_ids) == len(set(cue_ids)) and set(cue_ids) == set(EXPECTED_TARGET_IDENTITY),
        "rollout_identity_contract_failed": all(
            cue_id in EXPECTED_TARGET_IDENTITY
            and str(row.get("text") or "") == EXPECTED_TARGET_IDENTITY[cue_id][0]
            and int(row.get("start_frame") or -1) == EXPECTED_TARGET_IDENTITY[cue_id][1]
            and int(row.get("end_frame") or -1) == EXPECTED_TARGET_IDENTITY[cue_id][2]
            and str(row.get("name") or "") == f"VC_TEXTPLUS_{int(cue_id[-3:]):04d}_{cue_id}"
            for row, cue_id in zip(items, cue_ids)
        ),
        "rollout_target_contract_failed": len(targets) == 36 and center_count == 18 and size_count == 18,
        "rollout_property_contract_failed": properties == ALLOWED_OPERATION_PROPERTIES
        and all(not row.get("blend_targets") and set(str(value) for value in (row.get("write_inputs") or [])) == ALLOWED_OPERATION_PROPERTIES for row in items),
        "mutation_manifest_property_contract_failed": all(operation_input(row) in ALLOWED_OPERATION_PROPERTIES for row in manifest),
        "plan_property_contract_failed": set(contract.get("allowed_operation_properties") or []) == ALLOWED_OPERATION_PROPERTIES
        and contract.get("known_excluded_source_properties") == ["Blend"]
        and contract.get("unknown_properties_fail_closed") is True,
        "plan_summary_contract_failed": integer(summary.get("center_target_count"), 0) == 18
        and integer(summary.get("size_target_count"), 0) == 18
        and integer(summary.get("blend_target_count"), 0) == 0
        and integer(summary.get("other_property_target_count"), 0) == 0
        and integer(summary.get("total_target_count"), 0) == 36,
        "safety_contract_failed": all(bool(safety.get(key)) for key in (
            "only_contained_accepted_cues_writable", "timeline_item_boundaries_read_only",
            "other_v3_captions_read_only", "opacity_proxy_diagnostic_only", "z_order_read_only",
            "hard_outline_default_forbidden", "solid_outline_100pct_no_blur_forbidden",
            "center_size_property_allowlist_enforced", "unknown_properties_fail_closed",
        )) and safety.get("binary_visibility_gate_allowed") is False,
    }
    return [failure for failure, ok in checks.items() if not ok]


def safe_call(obj: Any, method: str, *args: Any, default: Any = None) -> Any:
    if obj is None:
        return default
    try:
        fn = getattr(obj, method)
        return fn(*args)
    except Exception:
        return default


def finite(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    try:
        attrs = value.GetAttrs() or {}
        if attrs:
            return {str(k): json_safe(v) for k, v in attrs.items()}
    except Exception:
        pass
    try:
        return str(value)
    except Exception:
        return None


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


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


def normalize_value(input_name: str, value: Any) -> Any:
    if input_name == "Center":
        return normalize_point(value)
    number = finite(value)
    return number if number is not None else json_safe(value)


def values_match(input_name: str, actual: Any, expected: Any, tolerance: float) -> bool:
    a = normalize_value(input_name, actual)
    e = normalize_value(input_name, expected)
    if input_name == "Center":
        return bool(a is not None and e is not None and len(a) == 2 and len(e) == 2 and all(abs(float(x) - float(y)) <= tolerance for x, y in zip(a, e)))
    af, ef = finite(a), finite(e)
    return af is not None and ef is not None and abs(af - ef) <= tolerance


def snapshots_match(actual: Any, expected: Any, tolerance: float = 1e-6) -> bool:
    if isinstance(actual, dict) and isinstance(expected, dict):
        return set(actual) == set(expected) and all(snapshots_match(actual[k], expected[k], tolerance) for k in actual)
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(snapshots_match(a, e, tolerance) for a, e in zip(actual, expected))
    af, ef = finite(actual), finite(expected)
    if af is not None and ef is not None:
        return abs(af - ef) <= tolerance
    return actual == expected


def default_config() -> Dict[str, Any]:
    root = Path(os.environ.get("VC_PROJECT_ROOT", DEFAULT_PROJECT_ROOT))
    video_id = os.environ.get("VC_VIDEO_ID", DEFAULT_VIDEO_ID)
    analysis = root / "data" / video_id / "analysis"
    davinci = root / "data" / video_id / "davinci"
    return {
        "project_root": str(root),
        "video_id": video_id,
        "plan_path": str(analysis / f"{video_id}_caption_source_geometry_contained_plan_step_3B_6D.json"),
        "latest_report_path": str(davinci / f"{video_id}_resolve_source_geometry_contained_step_3B_6D_report.json"),
        "first_report_path": str(davinci / f"{video_id}_resolve_source_geometry_contained_step_3B_6D_first_application_report.json"),
        "idempotency_report_path": str(davinci / f"{video_id}_resolve_source_geometry_contained_step_3B_6D_idempotency_report.json"),
        "state_path": str(davinci / f"{video_id}_resolve_source_geometry_contained_step_3B_6D_state.json"),
        "workspace_status_path": str(davinci / f"{video_id}_resolve_source_geometry_contained_step_3B_6D_workspace_status.json"),
        "workspace_log_path": str(davinci / f"{video_id}_resolve_source_geometry_contained_step_3B_6D_workspace.log"),
        "workspace_lock_path": str(davinci / f"{video_id}_resolve_source_geometry_contained_step_3B_6D_workspace.lock"),
        "expected_v3_count": 116,
        "value_tolerance": 1e-5,
        "save_settle_sec": 1.5,
        "rollback_on_failure": True,
        "show_completion_message": True,
    }


def config_path() -> Path:
    env = os.environ.get("VC_STEP_3B6D_CONFIG")
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
    value = safe_call(item, "GetStart", default=None)
    return int(value) if value is not None else None


def item_end(item: Any) -> Optional[int]:
    value = safe_call(item, "GetEnd", default=None)
    return int(value) if value is not None else None


def track_items(timeline: Any, track_type: str, index: int) -> List[Any]:
    value = safe_call(timeline, "GetItemListInTrack", track_type, index, default=[])
    return list(value or [])


def scan_tracks(timeline: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for track_type in ("video", "audio", "subtitle"):
        count = int(safe_call(timeline, "GetTrackCount", track_type, default=0) or 0)
        rows = []
        for index in range(1, count + 1):
            rows.append({
                "index": index,
                "items": [
                    {"name": item_name(item), "start": item_start(item), "end": item_end(item)}
                    for item in track_items(timeline, track_type, index)
                ],
            })
        result[track_type] = rows
    return result


def scan_v3(timeline: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    count = int(safe_call(timeline, "GetTrackCount", "video", default=0) or 0)
    for index in range(1, count + 1):
        for item in track_items(timeline, "video", index):
            name = item_name(item)
            if name.startswith("VC_TEXTPLUS_"):
                result[name] = item
    return result


def v3_ranges(items: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sorted(
        [{"name": name, "start": item_start(item), "end": item_end(item)} for name, item in items.items()],
        key=lambda row: (row.get("start") if row.get("start") is not None else -1, row.get("name") or ""),
    )


def fusion_comp(item: Any) -> Any:
    count = int(safe_call(item, "GetFusionCompCount", default=0) or 0)
    if count > 0:
        comp = safe_call(item, "GetFusionCompByIndex", 1, default=None)
        if comp is not None:
            return comp
    return safe_call(item, "GetFusionCompByName", "Composition 1", default=None)


def textplus_tool(comp: Any) -> Any:
    if comp is None:
        return None
    tools = safe_call(comp, "GetToolList", False, default={}) or {}
    entries: Iterable[Any] = tools.values() if isinstance(tools, dict) else tools
    for tool in entries:
        attrs = safe_call(tool, "GetAttrs", default={}) or {}
        reg_id = str(attrs.get("TOOLS_RegID") or attrs.get("TOOLST_RegID") or "")
        name = str(attrs.get("TOOLS_Name") or "")
        if reg_id in ("TextPlus", "Text3D") or name.lower() in ("template", "text+"):
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
    entries: Iterable[Any] = raw.values() if isinstance(raw, dict) else raw
    for row in entries:
        attrs = safe_call(row, "GetAttrs", default={}) or {}
        candidate = str(attrs.get("INPS_ID") or attrs.get("INPS_Name") or "")
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


def ensure_modifier(comp: Any, tool: Any, input_name: str) -> Dict[str, Any]:
    input_object = find_input(tool, input_name)
    if input_object is None:
        return {"ok": False, "created": False, "failure": f"input_not_found:{input_name}"}
    if connected_output(input_object) is not None:
        return {"ok": True, "created": False, "modifier": "existing_connected_modifier"}
    modifier = "Path" if input_name == "Center" else "BezierSpline"
    attempts: List[Dict[str, Any]] = []
    try:
        returned = tool.AddModifier(input_name, modifier)
        attempts.append({"method": "Tool.AddModifier", "returned": str(returned), "modifier": modifier})
    except Exception as exc:
        attempts.append({"method": "Tool.AddModifier", "error": f"{type(exc).__name__}: {exc}", "modifier": modifier})
    time.sleep(0.05)
    if connected_output(find_input(tool, input_name)) is not None:
        return {"ok": True, "created": True, "modifier": modifier, "attempts": attempts}
    try:
        factory = getattr(comp, modifier)
        setattr(tool, input_name, factory())
        attempts.append({"method": f"comp.{modifier}()", "assigned": True})
    except Exception as exc:
        attempts.append({"method": f"comp.{modifier}()", "error": f"{type(exc).__name__}: {exc}"})
    time.sleep(0.05)
    ok = connected_output(find_input(tool, input_name)) is not None
    return {"ok": ok, "created": ok, "modifier": modifier, "attempts": attempts, "failure": None if ok else f"modifier_not_connected:{input_name}"}


def fusion_variants(input_name: str, expected: Any) -> List[Any]:
    if input_name == "Center":
        point = normalize_point(expected)
        if point is None:
            return []
        x, y = point
        variants: List[Any] = []
        bmd_obj = globals().get("bmd")
        if bmd_obj is not None:
            try:
                variants.append(bmd_obj.Point(x, y))
            except Exception:
                pass
        variants.extend(([x, y], {1: x, 2: y, 3: 0.0}, {1: x, 2: y}))
        return variants
    value = finite(expected)
    return [value] if value is not None else []


def write_key(tool: Any, input_name: str, frame: int, expected: Any, tolerance: float) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    input_object = find_input(tool, input_name)
    for variant in fusion_variants(input_name, expected):
        if input_object is not None:
            try:
                input_object[int(frame)] = variant
                actual = read_input(tool, input_name, int(frame))
                matched = values_match(input_name, actual, expected, tolerance)
                attempts.append({"method": "Input[frame]=value", "frame": int(frame), "variant": str(variant), "actual": json_safe(actual), "matched": matched})
                if matched:
                    return {"ok": True, "attempts": attempts}
            except Exception as exc:
                attempts.append({"method": "Input[frame]=value", "frame": int(frame), "variant": str(variant), "error": f"{type(exc).__name__}: {exc}"})
        try:
            returned = tool.SetInput(input_name, variant, int(frame))
            actual = read_input(tool, input_name, int(frame))
            matched = values_match(input_name, actual, expected, tolerance)
            attempts.append({"method": "Tool.SetInput(frame)", "frame": int(frame), "variant": str(variant), "returned": json_safe(returned), "actual": json_safe(actual), "matched": matched})
            if matched:
                return {"ok": True, "attempts": attempts}
        except Exception as exc:
            attempts.append({"method": "Tool.SetInput(frame)", "frame": int(frame), "variant": str(variant), "error": f"{type(exc).__name__}: {exc}"})
    return {"ok": False, "attempts": attempts, "actual": json_safe(read_input(tool, input_name, int(frame)))}


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


def shading_snapshot(tool: Any) -> Dict[str, Any]:
    return {
        "outline": {
            "Enabled2": read_candidates(tool, ("Enabled2",)),
            "ElementShape2": read_candidates(tool, ("ElementShape2", "Appearance2")),
            "Red2": read_candidates(tool, ("Red2",)),
            "Green2": read_candidates(tool, ("Green2",)),
            "Blue2": read_candidates(tool, ("Blue2",)),
            "Alpha2": read_candidates(tool, ("Alpha2", "Opacity2")),
            "Thickness2": read_candidates(tool, ("Thickness2",)),
            "OutsideOnly2": read_candidates(tool, ("OutsideOnly2",)),
        },
        "shadow": {
            "Enabled3": read_candidates(tool, ("Enabled3",)),
            "ElementShape3": read_candidates(tool, ("ElementShape3", "Appearance3")),
            "Red3": read_candidates(tool, ("Red3",)),
            "Green3": read_candidates(tool, ("Green3",)),
            "Blue3": read_candidates(tool, ("Blue3",)),
            "Opacity3": read_candidates(tool, ("Opacity3", "Alpha3")),
            "Offset3": read_candidates(tool, ("Offset3",)),
            "SoftnessX3": read_candidates(tool, ("SoftnessX3", "Softness3")),
            "SoftnessY3": read_candidates(tool, ("SoftnessY3",)),
        },
    }


def layout_snapshot(tool: Any) -> Dict[str, Any]:
    names = ("LayoutType", "HAnchor", "VAnchor", "Angle", "CharacterSpacing", "LineSpacing", "Width", "Height", "UseFrameFormatSettings")
    return {name: json_safe(read_input(tool, name)) for name in names if find_input(tool, name) is not None}


def compact_item_snapshot(item: Any, tool: Any) -> Dict[str, Any]:
    return {
        "identity": identity_snapshot(item, tool),
        "center_frame_0": json_safe(read_input(tool, "Center", 0)),
        "center_modifier_connected": connected_output(find_input(tool, "Center")) is not None,
        "size_frame_0": json_safe(read_input(tool, "Size", 0)),
        "size_modifier_connected": connected_output(find_input(tool, "Size")) is not None,
        "blend_frame_0": json_safe(read_input(tool, "Blend", 0)) if find_input(tool, "Blend") is not None else None,
        "blend_modifier_connected": connected_output(find_input(tool, "Blend")) is not None if find_input(tool, "Blend") is not None else False,
        "fill": fill_snapshot(tool),
        "shading": shading_snapshot(tool),
        "layout": layout_snapshot(tool),
    }


def target_values(tool: Any, targets: Sequence[Dict[str, Any]], tolerance: float) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for target in targets:
        input_name = str(target.get("input"))
        frame = int(target.get("local_frame") or 0)
        expected = target.get("expected")
        obj = find_input(tool, input_name)
        actual = read_input(tool, input_name, frame)
        connected = connected_output(obj) is not None
        matched = values_match(input_name, actual, expected, tolerance)
        rows.append({
            "input": input_name,
            "local_frame": frame,
            "timeline_frame": target.get("timeline_frame"),
            "expected": json_safe(expected),
            "actual": json_safe(actual),
            "modifier_connected": connected,
            "matched": matched,
            "present": bool(connected and matched),
        })
    return rows


def protected_animation_snapshot(acquired: Dict[str, Tuple[Any, Any, Any]], protected: Sequence[Dict[str, Any]], tolerance: float) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in protected:
        name = str(item.get("name") or "")
        if name not in acquired:
            rows.append({"name": name, "cue_id": item.get("cue_id"), "present": False, "targets": []})
            continue
        tool = acquired[name][2]
        targets = target_values(tool, item.get("targets") or [], tolerance)
        rows.append({"name": name, "cue_id": item.get("cue_id"), "present": bool(targets and all(row.get("present") for row in targets)), "targets": targets})
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



def write_runtime_status(path: Path, payload: Dict[str, Any]) -> None:
    write_json(path, payload)


def run() -> Dict[str, Any]:
    started = time.time()
    cfg_path, cfg = load_config()
    plan_path = Path(cfg["plan_path"]).resolve()
    latest_path = Path(cfg["latest_report_path"]).resolve()
    first_path = Path(cfg["first_report_path"]).resolve()
    idempotency_path = Path(cfg["idempotency_report_path"]).resolve()
    state_path = Path(cfg["state_path"]).resolve()
    status_path = Path(cfg["workspace_status_path"]).resolve()
    log_path = Path(cfg["workspace_log_path"]).resolve()
    lock_path = Path(cfg["workspace_lock_path"]).resolve()
    expected_v3 = int(cfg.get("expected_v3_count") or 116)
    tolerance = float(cfg.get("value_tolerance") or 1e-5)
    settle = float(cfg.get("save_settle_sec") or 1.5)
    run_id = f"{int(now_unix())}_{os.getpid()}"

    report: Dict[str, Any] = {
        "ok": False,
        "step": "Major Step 3B.6D",
        "workspace_version": VERSION,
        "config_path": str(cfg_path),
        "plan_path": str(plan_path),
        "run_id": run_id,
        "started_at_unix": now_unix(),
        "failures": [],
        "warnings": [],
    }

    if lock_path.exists():
        report["failures"] = ["workspace_lock_exists"]
        write_json(latest_path, report)
        return report
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(run_id, encoding="utf-8")

    try:
        plan = load_json(plan_path)
        if not plan.get("ok") or plan.get("schema") != EXPECTED_SCHEMA:
            report["failures"].append("plan_gate_failed")
        if str(plan.get("plan_hash") or "") != canonical_hash(plan, ignored=("created_at_unix",)):
            report["failures"].append("plan_hash_failed")
        rollout_items = list(plan.get("rollout_items") or [])
        report["failures"].extend(executable_plan_failures(plan))
        if report["failures"]:
            raise StopIteration

        write_runtime_status(status_path, {
            "ok": False, "running": True, "step": "Major Step 3B.6D", "version": VERSION,
            "run_id": run_id, "stage": "acquiring_timeline", "current": 0, "total": 4,
        })
        append_log(log_path, "workspace_started", {"run_id": run_id, "rollout_count": len(rollout_items)})

        resolve_app = get_resolve()
        manager = resolve_app.GetProjectManager()
        project = manager.GetCurrentProject()
        if project is None:
            raise RuntimeError("No Resolve project is open.")
        timeline = project.GetCurrentTimeline()
        if timeline is None:
            raise RuntimeError("No Resolve timeline is open.")

        tracks_before = scan_tracks(timeline)
        acquired_before = acquire_all(timeline, expected_v3)
        ranges_before = v3_ranges({name: row[0] for name, row in acquired_before.items()})
        target_names = {str(row.get("name")) for row in rollout_items}
        if any(name not in acquired_before for name in target_names):
            missing = sorted(name for name in target_names if name not in acquired_before)
            raise RuntimeError(f"Rollout item(s) not found: {missing}")

        snapshots_before: Dict[str, Dict[str, Any]] = {
            name: compact_item_snapshot(item, tool)
            for name, (item, _comp, tool) in acquired_before.items()
        }
        protected_before = protected_animation_snapshot(
            acquired_before, plan.get("protected_animation_targets") or [], tolerance
        )
        missing_protected_before = [row for row in protected_before if not row.get("present")]
        if missing_protected_before:
            report["failures"].append("step_3C_protected_animation_preflight_failed")
            report["protected_animation_preflight"] = missing_protected_before
            raise StopIteration

        per_item_before: List[Dict[str, Any]] = []
        baseline_by_name: Dict[str, List[Dict[str, Any]]] = {}
        topology_before: Dict[str, Dict[str, bool]] = {}
        already_correct_by_name: Dict[str, bool] = {}
        for item_plan in rollout_items:
            name = str(item_plan.get("name"))
            item, _comp, tool = acquired_before[name]
            actual_range = (item_start(item), item_end(item))
            expected_range = (int(item_plan.get("start_frame") or 0), int(item_plan.get("end_frame") or 0))
            if actual_range != expected_range:
                report["failures"].append(f"timeline_range_preflight_failed:{name}:{actual_range}:{expected_range}")
            targets = list(item_plan.get("targets") or [])
            target_rows = target_values(tool, targets, tolerance)
            already_correct = bool(target_rows and all(row.get("present") for row in target_rows))
            already_correct_by_name[name] = already_correct
            inputs = sorted(set(str(row.get("input")) for row in targets))
            topology_before[name] = {
                input_name: connected_output(find_input(tool, input_name)) is not None
                for input_name in inputs
            }
            baseline_by_name[name] = [
                {
                    "input": str(target.get("input")),
                    "local_frame": int(target.get("local_frame") or 0),
                    "value": json_safe(read_input(tool, str(target.get("input")), int(target.get("local_frame") or 0))),
                }
                for target in targets
            ]
            per_item_before.append({
                "cue_id": item_plan.get("cue_id"), "name": name, "text": item_plan.get("text"),
                "already_correct": already_correct, "targets": target_rows,
                "visibility": item_plan.get("visibility"), "inputs": inputs,
            })

        # Enforce the accepted 3B.6C baseline: AND must already carry the approved dense keys.
        and_row = next(row for row in per_item_before if row.get("cue_id") == "sub_114")
        if not and_row.get("already_correct"):
            report["failures"].append("step_3B_6C_AND_baseline_not_present")
        if report["failures"]:
            raise StopIteration

        all_already_correct = all(already_correct_by_name.values())
        run_mode = "idempotent_second_run" if all_already_correct else "first_application"
        mode_path = idempotency_path if all_already_correct else first_path
        report["run_mode"] = run_mode
        report["mode_report"] = str(mode_path)
        report["plan_hash"] = plan.get("plan_hash")
        report["warnings"] = list(plan.get("warnings") or [])

        write_results: List[Dict[str, Any]] = []
        modifiers: Dict[str, Any] = {}
        modified_names: List[str] = []
        for index, item_plan in enumerate(rollout_items, start=1):
            name = str(item_plan.get("name"))
            if already_correct_by_name[name]:
                continue
            write_runtime_status(status_path, {
                "ok": False, "running": True, "step": "Major Step 3B.6D", "version": VERSION,
                "run_id": run_id, "run_mode": run_mode, "stage": "apply_dense_geometry",
                "current": index, "total": len(rollout_items), "current_caption": item_plan.get("cue_id"),
                "elapsed_seconds": round(time.time() - started, 2),
            })
            _item, comp, tool = acquired_before[name]
            item_modifiers: Dict[str, Any] = {}
            safe_call(comp, "Lock", default=None)
            try:
                for input_name in sorted(set(str(row.get("input")) for row in item_plan.get("targets") or [])):
                    modifier = ensure_modifier(comp, tool, input_name)
                    item_modifiers[input_name] = modifier
                    if not modifier.get("ok"):
                        report["failures"].append(modifier.get("failure") or f"modifier_failed:{name}:{input_name}")
                        continue
                    for target in sorted(
                        (row for row in item_plan.get("targets") or [] if str(row.get("input")) == input_name),
                        key=lambda row: int(row.get("local_frame") or 0),
                    ):
                        result = write_key(
                            tool, input_name, int(target.get("local_frame") or 0),
                            target.get("expected"), tolerance
                        )
                        write_results.append({
                            "cue_id": item_plan.get("cue_id"), "name": name,
                            "target": target, "result": result,
                        })
                        if not result.get("ok"):
                            report["failures"].append(
                                f"key_write_failed:{name}:{input_name}@{target.get('local_frame')}"
                            )
            finally:
                safe_call(comp, "Unlock", default=None)
            modifiers[name] = item_modifiers
            modified_names.append(name)

        write_runtime_status(status_path, {
            "ok": False, "running": True, "step": "Major Step 3B.6D", "version": VERSION,
            "run_id": run_id, "run_mode": run_mode, "stage": "save_and_persistent_readback",
            "current": len(rollout_items), "total": len(rollout_items),
            "elapsed_seconds": round(time.time() - started, 2),
        })
        save_ok = safe_call(manager, "SaveProject", default=False) is not False
        if not save_ok:
            report["failures"].append("project_save_failed")
        time.sleep(settle)

        timeline_after = project.GetCurrentTimeline()
        acquired_after = acquire_all(timeline_after, expected_v3)
        ranges_after = v3_ranges({name: row[0] for name, row in acquired_after.items()})
        tracks_after = scan_tracks(timeline_after)
        snapshots_after: Dict[str, Dict[str, Any]] = {
            name: compact_item_snapshot(item, tool)
            for name, (item, _comp, tool) in acquired_after.items()
        }
        protected_after = protected_animation_snapshot(
            acquired_after, plan.get("protected_animation_targets") or [], tolerance
        )

        per_item_after: List[Dict[str, Any]] = []
        target_failures: List[str] = []
        for item_plan in rollout_items:
            name = str(item_plan.get("name"))
            item, _comp, tool = acquired_after[name]
            targets = target_values(tool, item_plan.get("targets") or [], tolerance)
            for row in targets:
                if not row.get("present"):
                    target_failures.append(
                        f"key_readback_failed:{name}:{row.get('input')}@{row.get('local_frame')}"
                    )
            per_item_after.append({
                "cue_id": item_plan.get("cue_id"), "name": name, "text": item_plan.get("text"),
                "targets": targets, "all_present": bool(targets and all(row.get("present") for row in targets)),
                "actual_start": item_start(item), "actual_end": item_end(item),
            })
        report["failures"].extend(target_failures)

        protected_changes: List[str] = []
        for name in sorted(snapshots_before):
            before = snapshots_before[name]
            after = snapshots_after.get(name)
            if after is None:
                protected_changes.append(f"missing_after:{name}")
                continue
            if name in target_names:
                for field in ("identity", "fill", "shading", "layout"):
                    if not snapshots_match(after.get(field), before.get(field), tolerance):
                        protected_changes.append(f"target_protected_changed:{field}:{name}")
            else:
                if not snapshots_match(after, before, tolerance):
                    protected_changes.append(f"non_rollout_changed:{name}")
        report["failures"].extend(protected_changes)

        protected_ok = snapshots_match(protected_after, protected_before, tolerance)
        if not protected_ok:
            report["failures"].append("step_3C_protected_animation_changed")
        track_ok = snapshots_match(tracks_after, tracks_before, tolerance)
        ranges_ok = snapshots_match(ranges_after, ranges_before, tolerance)
        if not track_ok:
            report["failures"].append("timeline_track_integrity_failed")
        if not ranges_ok:
            report["failures"].append("v3_track_integrity_failed")

        rollback: Dict[str, Any] = {"attempted": False, "ok": None, "items": []}
        if report["failures"] and cfg.get("rollback_on_failure", True) and modified_names:
            rollback["attempted"] = True
            current = acquire_all(project.GetCurrentTimeline(), expected_v3)
            rollback_rows: List[Dict[str, Any]] = []
            for name in modified_names:
                _item, comp, tool = current[name]
                safe_call(comp, "Lock", default=None)
                try:
                    for baseline in baseline_by_name[name]:
                        result = write_key(
                            tool, baseline["input"], baseline["local_frame"],
                            baseline["value"], tolerance
                        )
                        rollback_rows.append({"name": name, **baseline, "result": result})
                finally:
                    safe_call(comp, "Unlock", default=None)
            rollback_save = safe_call(manager, "SaveProject", default=False) is not False
            time.sleep(settle)
            rollback["items"] = rollback_rows
            rollback["save_ok"] = rollback_save
            rollback["ok"] = bool(
                rollback_save and all(row.get("result", {}).get("ok") for row in rollback_rows)
            )

        target_rows_after = [target for row in per_item_after for target in row.get("targets") or []]
        center_count = sum(1 for row in target_rows_after if row.get("input") == "Center" and row.get("present"))
        size_count = sum(1 for row in target_rows_after if row.get("input") == "Size" and row.get("present"))
        blend_count = sum(1 for row in target_rows_after if row.get("input") == "Blend" and row.get("present"))
        other_property_count = sum(1 for row in target_rows_after if row.get("input") not in ALLOWED_OPERATION_PROPERTIES)
        modified_count = sum(
            1 for row in per_item_after
            if not already_correct_by_name.get(str(row.get("name")), False) and row.get("all_present")
        )
        already_correct_count = sum(1 for value in already_correct_by_name.values() if value)
        non_rollout_failures = [
            row for row in protected_changes
            if row.startswith("non_rollout_changed") or row.startswith("missing_after")
        ]
        summary = {
            "v3_candidate_count": len(acquired_after),
            "accepted_source_instance_count": int((plan.get("summary") or {}).get("accepted_source_instance_count") or 0),
            "unresolved_source_instance_count": int((plan.get("summary") or {}).get("unresolved_source_instance_count") or 0),
            "timing_mismatch_excluded_count": int((plan.get("summary") or {}).get("timing_mismatch_excluded_count") or 0),
            "rollout_item_count": len(rollout_items),
            "mapped_count": len(per_item_after),
            "modified_count": modified_count,
            "already_correct_count": already_correct_count,
            "target_key_count": len(target_rows_after),
            "target_key_verified_count": sum(1 for row in target_rows_after if row.get("present")),
            "center_key_count": int((plan.get("summary") or {}).get("center_target_count") or 0),
            "center_key_verified_count": center_count,
            "size_key_count": int((plan.get("summary") or {}).get("size_target_count") or 0),
            "size_key_verified_count": size_count,
            "blend_key_count": int((plan.get("summary") or {}).get("blend_target_count") or 0),
            "blend_key_verified_count": blend_count,
            "other_property_key_count": other_property_count,
            "excluded_blend_target_count": int((plan.get("summary") or {}).get("excluded_blend_target_count") or 0),
            "visibility_gated_caption_count": int((plan.get("summary") or {}).get("visibility_gated_caption_count") or 0),
            "non_rollout_caption_count": expected_v3 - len(rollout_items),
            "non_rollout_caption_verified_count": expected_v3 - len(rollout_items) - len(non_rollout_failures),
            "protected_animation_caption_count": len(protected_after),
            "protected_animation_verified_count": sum(1 for row in protected_after if row.get("present")),
            "protected_animation_target_count": sum(len(row.get("targets") or []) for row in protected_after),
            "protected_animation_target_verified_count": sum(
                sum(1 for target in row.get("targets") or [] if target.get("present"))
                for row in protected_after
            ),
            "opacity_proxy_applied_count": 0,
            "binary_visibility_target_count": 0,
            "z_order_write_count": 0,
            "timeline_boundary_write_count": 0,
            "timeline_integrity_failure_count": (0 if track_ok else 1) + (0 if ranges_ok else 1),
            "protected_integrity_failure_count": len(protected_changes) + (0 if protected_ok else 1),
            "rollback_performed_count": 1 if rollback.get("attempted") else 0,
            "failed_count": len(report["failures"]),
        }

        ok = not report["failures"]
        report.update({
            "ok": ok,
            "project_name": safe_call(project, "GetName", default=None),
            "timeline_name": safe_call(timeline_after, "GetName", default=None),
            "summary": summary,
            "items_before": per_item_before,
            "items_after": per_item_after,
            "modifiers": modifiers,
            "writes": write_results,
            "protected_animation_before": protected_before,
            "protected_animation_after": protected_after,
            "track_integrity": {"ok": track_ok, "before": tracks_before, "after": tracks_after},
            "v3_track_integrity": {"ok": ranges_ok, "before": ranges_before, "after": ranges_after},
            "protected_integrity_failures": protected_changes,
            "save_ok": save_ok,
            "rollback": rollback,
            "runtime_seconds": round(time.time() - started, 3),
        })
        write_json(latest_path, report)
        write_json(mode_path, report)
        if ok:
            write_json(state_path, {
                "ok": True,
                "step": "Major Step 3B.6D",
                "workspace_version": VERSION,
                "plan_hash": plan.get("plan_hash"),
                "rollout_cue_ids": [row.get("cue_id") for row in rollout_items],
                "last_run_mode": run_mode,
                "last_report": str(mode_path),
                "updated_at_unix": now_unix(),
            })
        status = {
            "ok": ok, "running": False, "step": "Major Step 3B.6D", "version": VERSION,
            "run_id": run_id, "run_mode": run_mode, "finished_at_unix": now_unix(),
            "report": str(latest_path), "mode_report": str(mode_path),
            "summary": summary, "failures": report["failures"],
        }
        write_json(status_path, status)
        append_log(log_path, "workspace_finished", status)
        return report

    except StopIteration:
        report["runtime_seconds"] = round(time.time() - started, 3)
        write_json(latest_path, report)
        status = {
            "ok": False, "running": False, "step": "Major Step 3B.6D", "version": VERSION,
            "run_id": run_id, "failures": report.get("failures") or [], "report": str(latest_path),
        }
        write_json(status_path, status)
        append_log(log_path, "workspace_preflight_failed", status)
        return report
    except Exception as exc:
        report.update({
            "ok": False,
            "run_mode": report.get("run_mode", "exception"),
            "failures": list(report.get("failures") or []) + ["workspace_exception"],
            "exception": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "runtime_seconds": round(time.time() - started, 3),
        })
        write_json(latest_path, report)
        status = {
            "ok": False, "running": False, "step": "Major Step 3B.6D", "version": VERSION,
            "run_id": run_id, "report": str(latest_path),
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
            "Video Cloner — Step 3B.6D contained geometry rollout complete",
            "Contained source geometry/visibility rollout finished.\n\n"
            f"V3 clips: {summary.get('v3_candidate_count', 0)}\n"
            f"Rollout captions: {summary.get('rollout_item_count', 0)}\n"
            f"Modified: {summary.get('modified_count', 0)}\n"
            f"Already correct: {summary.get('already_correct_count', 0)}\n"
            f"Center keys verified: {summary.get('center_key_verified_count', 0)}/{summary.get('center_key_count', 0)}\n"
            f"Size keys verified: {summary.get('size_key_verified_count', 0)}/{summary.get('size_key_count', 0)}\n"
            f"Forbidden Blend keys: {summary.get('blend_key_count', 0)}\n"
            f"Other V3 captions preserved: {summary.get('non_rollout_caption_verified_count', 0)}/{summary.get('non_rollout_caption_count', 0)}\n"
            f"Step 3C targets preserved: {summary.get('protected_animation_target_verified_count', 0)}/{summary.get('protected_animation_target_count', 0)}\n"
            f"Boundary-mismatch cues excluded: {summary.get('timing_mismatch_excluded_count', 0)}\n"
            f"Failures: {summary.get('failed_count', 0)}\n\n"
            "Timeline item boundaries and z-order were not modified.\n"
            f"Mode report:\n{report.get('mode_report')}",
            error=False,
        )
    else:
        show_message(
            "Video Cloner — Step 3B.6D contained geometry rollout failed",
            "The contained geometry/visibility rollout did not pass.\n\n"
            f"Failures:\n- " + "\n- ".join(report.get("failures") or ["unknown_failure"]) + "\n\n"
            f"Report:\n{report.get('mode_report') or report.get('plan_path')}",
            error=True,
        )


_AUTORUN_DONE = False


def _workspace_autorun() -> None:
    global _AUTORUN_DONE
    if _AUTORUN_DONE:
        return
    _AUTORUN_DONE = True
    try:
        main()
    except Exception as exc:
        show_message("Video Cloner — Step 3B.6D workspace exception", f"{type(exc).__name__}: {exc}", error=True)


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1":
    _workspace_autorun()
