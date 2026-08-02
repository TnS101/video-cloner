#!/usr/bin/env python3
"""Video Cloner — Major Step 3B.3A Resolve outline/shadow safety probe.

This Workspace script changes exactly one existing V3 Text+ caption (sub_019).
It materializes Resolve-owned secondary Text+ shading slots, writes only the
real element-specific inputs, archives first-run and second-run reports, and
verifies persistence while preserving Step 3C animation, fill, layout, timing,
caption identity, and all timeline tracks.

Run from DaVinci Resolve Studio 21:
    Workspace -> Scripts -> resolve_apply_caption_outline_shadow_probe_step_3B_3
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

VERSION = "resolve_caption_outline_shadow_step_3B_3A_v1_3_direct_slot_materialization"
DEFAULT_PROJECT_ROOT = r"C:\Users\User\Downloads\Projects\Video Cloner"
DEFAULT_VIDEO_ID = "DZsqH7auhjt"
DEFAULT_CONFIG_NAME = "resolve_caption_outline_shadow_step_3B_3_config.json"
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
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


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
        return bool(
            actual_point is not None
            and abs(actual_point[0] - expected_point[0]) <= tolerance
            and abs(actual_point[1] - expected_point[1]) <= tolerance
        )
    if isinstance(expected, str):
        return normalize_token(actual) == normalize_token(expected)
    expected_number = finite(expected)
    if expected_number is not None:
        actual_number = finite(actual)
        return actual_number is not None and abs(actual_number - expected_number) <= tolerance
    return json_safe(actual) == json_safe(expected)



def snapshots_match(actual: Any, expected: Any, tolerance: float = 1e-6) -> bool:
    """Recursively compare Resolve snapshots with numeric/point tolerance."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual.keys()) != set(expected.keys()):
            return False
        return all(
            snapshots_match(actual.get(key), value, tolerance)
            for key, value in expected.items()
        )
    if isinstance(expected, (list, tuple)):
        if not isinstance(actual, (list, tuple)) or len(actual) != len(expected):
            return False
        return all(
            snapshots_match(a, e, tolerance)
            for a, e in zip(actual, expected)
        )
    return values_match(actual, expected, tolerance)


def parse_hex_color(value: Any) -> Tuple[float, float, float]:
    text = str(value or "#000000").strip().lstrip("#")
    if len(text) != 6:
        text = "000000"
    try:
        return tuple(round(int(text[index:index + 2], 16) / 255.0, 8) for index in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (0.0, 0.0, 0.0)


def point_variants(value: Sequence[float]) -> List[Any]:
    x, y = float(value[0]), float(value[1])
    return [{1: x, 2: y, 3: 0.0}, {1: x, 2: y}, [x, y]]


def default_config() -> Dict[str, Any]:
    root = Path(os.environ.get("VC_PROJECT_ROOT", DEFAULT_PROJECT_ROOT))
    video_id = os.environ.get("VC_VIDEO_ID", DEFAULT_VIDEO_ID)
    data_root = root / "data" / video_id
    analysis = data_root / "analysis"
    davinci = data_root / "davinci"
    return {
        "project_root": str(root),
        "video_id": video_id,
        "plan_path": str(analysis / f"{video_id}_caption_outline_shadow_plan_step_3B_3.json"),
        "latest_report_path": str(davinci / f"{video_id}_resolve_outline_shadow_step_3B_3_report.json"),
        "first_report_path": str(davinci / f"{video_id}_resolve_outline_shadow_step_3B_3_first_application_report.json"),
        "idempotency_report_path": str(davinci / f"{video_id}_resolve_outline_shadow_step_3B_3_idempotency_report.json"),
        "state_path": str(davinci / f"{video_id}_resolve_outline_shadow_step_3B_3_state.json"),
        "workspace_status_path": str(davinci / f"{video_id}_resolve_outline_shadow_step_3B_3_workspace_status.json"),
        "workspace_log_path": str(davinci / f"{video_id}_resolve_outline_shadow_step_3B_3_workspace.log"),
        "expected_v3_count": 116,
        "probe_cue_id": "sub_019",
        "outline_element": 2,
        "shadow_element": 3,
        "readback_delay_sec": 0.10,
        "save_settle_sec": 1.0,
        "value_tolerance": 1e-6,
        "animation_value_tolerance": 1e-5,
        "rollback_on_failure": True,
        "show_completion_message": True,
    }


def config_path() -> Path:
    environment = os.environ.get("VC_STEP_3B3_CONFIG")
    if environment:
        return Path(environment).expanduser().resolve()
    root = Path(os.environ.get("VC_PROJECT_ROOT", DEFAULT_PROJECT_ROOT))
    video_id = os.environ.get("VC_VIDEO_ID", DEFAULT_VIDEO_ID)
    candidates = [root / "data" / video_id / "davinci" / DEFAULT_CONFIG_NAME]
    script_path = globals().get("__file__")
    if script_path:
        candidates.append(Path(str(script_path)).resolve().with_name(DEFAULT_CONFIG_NAME))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def load_config() -> Tuple[Path, Dict[str, Any]]:
    path = config_path()
    config = default_config()
    if path.is_file():
        config.update(load_json(path))
    return path, config


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
    raise RuntimeError("Resolve API unavailable. Run this script from Workspace -> Scripts.")


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
            snapshot[f"{prefix}{index}"] = [
                {"name": item_name(item), "start": item_start(item), "end": item_end(item)}
                for item in track_items(timeline, track_type, index)
            ]
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
    return [
        {"name": name, "start": item_start(items[name]), "end": item_end(items[name])}
        for name in sorted(items)
    ]


def fusion_comp(item: Any) -> Any:
    comp = safe_call(item, "GetFusionCompByIndex", 1, default=None)
    if comp is not None:
        return comp
    names = safe_call(item, "GetFusionCompNameList", default=[]) or []
    for name in names:
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
    input_object = safe_call(tool, "FindInput", input_name, default=None)
    if input_object is not None:
        return input_object
    try:
        input_object = getattr(tool, input_name)
        if input_object is not None:
            return input_object
    except Exception:
        pass
    inputs = safe_call(tool, "GetInputList", default={}) or {}
    if isinstance(inputs, dict):
        for key, row in inputs.items():
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
        if value is not None:
            return value
    else:
        value = safe_call(tool, "GetInput", input_name, int(frame), default=None)
        if value is not None:
            return value
    input_object = find_input(tool, input_name)
    if input_object is not None:
        try:
            return input_object[int(frame or 0)]
        except Exception:
            pass
    return None


def input_inventory(tool: Any) -> Dict[str, Any]:
    raw = safe_call(tool, "GetInputList", default={}) or {}
    rows: List[Dict[str, Any]] = []
    entries: Iterable[Any] = raw.items() if isinstance(raw, dict) else enumerate(raw or [])
    keep_attrs = (
        "INPS_ID", "INPS_Name", "INPS_DataType", "INPB_Active", "INPB_Disabled",
        "INPB_External", "INPB_Connected", "INPB_IC_Visible", "INPB_PC_Visible",
        "INPN_Default", "INPN_MinAllowed", "INPN_MaxAllowed", "INPB_Integer",
        "INPID_InputControl", "INPS_ICS_ControlPage", "INPS_IC_Name",
    )
    for key, input_object in entries:
        attrs = safe_call(input_object, "GetAttrs", default={}) or {}
        input_id = str(attrs.get("INPS_ID") or key or attrs.get("INPS_Name") or "").strip()
        rows.append({
            "id": input_id,
            "name": str(attrs.get("INPS_Name") or input_id),
            "data_type": attrs.get("INPS_DataType"),
            "control_page": attrs.get("INPS_IC_ControlPage") or attrs.get("INPS_ControlPage") or attrs.get("INPS_ICS_ControlPage"),
            "control_group": attrs.get("INPS_IC_ControlGroup") or attrs.get("INPS_ControlGroup"),
            "attrs": {key: json_safe(attrs.get(key)) for key in keep_attrs if key in attrs},
        })
    return {
        "available": bool(rows),
        "input_count": len(rows),
        "input_ids": [row["id"] for row in rows],
        "inputs": rows,
    }

def candidate_variants(expected: Any) -> List[Any]:
    point = normalize_point(expected)
    return point_variants(point) if point is not None else [expected]


def write_input(tool: Any, input_name: str, expected: Any, tolerance: float) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    for variant in candidate_variants(expected):
        try:
            returned = tool.SetInput(input_name, variant)
            actual = read_input(tool, input_name)
            matched = values_match(actual, expected, tolerance)
            attempts.append({"method": "Tool.SetInput", "variant": json_safe(variant), "returned": json_safe(returned), "actual": json_safe(actual), "matched": matched})
            if matched:
                return {"ok": True, "input": input_name, "expected": json_safe(expected), "actual": json_safe(actual), "attempts": attempts}
        except Exception as exc:
            attempts.append({"method": "Tool.SetInput", "variant": json_safe(variant), "error": f"{type(exc).__name__}: {exc}"})

        input_object = find_input(tool, input_name)
        if input_object is not None:
            try:
                input_object[0] = variant
                actual = read_input(tool, input_name)
                matched = values_match(actual, expected, tolerance)
                attempts.append({"method": "Input[0]=value", "variant": json_safe(variant), "actual": json_safe(actual), "matched": matched})
                if matched:
                    return {"ok": True, "input": input_name, "expected": json_safe(expected), "actual": json_safe(actual), "attempts": attempts}
            except Exception as exc:
                attempts.append({"method": "Input[0]=value", "variant": json_safe(variant), "error": f"{type(exc).__name__}: {exc}"})

        try:
            setattr(tool, input_name, variant)
            actual = read_input(tool, input_name)
            matched = values_match(actual, expected, tolerance)
            attempts.append({"method": "setattr(tool,input,value)", "variant": json_safe(variant), "actual": json_safe(actual), "matched": matched})
            if matched:
                return {"ok": True, "input": input_name, "expected": json_safe(expected), "actual": json_safe(actual), "attempts": attempts}
        except Exception as exc:
            attempts.append({"method": "setattr(tool,input,value)", "variant": json_safe(variant), "error": f"{type(exc).__name__}: {exc}"})

    return {"ok": False, "input": input_name, "expected": json_safe(expected), "actual": json_safe(read_input(tool, input_name)), "attempts": attempts}


def write_candidates(tool: Any, candidates: Sequence[str], expected: Any, tolerance: float, required: bool = True) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    for candidate in candidates:
        result = write_input(tool, candidate, expected, tolerance)
        attempts.append(result)
        if result.get("ok"):
            return {"ok": True, "required": required, "candidates": list(candidates), "resolved_input": candidate, "expected": json_safe(expected), "actual": result.get("actual"), "attempts": attempts}
    return {"ok": False, "required": required, "candidates": list(candidates), "resolved_input": None, "expected": json_safe(expected), "attempts": attempts}

SELECTOR_INPUTS: Tuple[str, ...] = ("SelectElement", "Select")
ELEMENT_PROXY_SUFFIX = "1"


def selector_snapshot(tool: Any) -> Dict[str, Any]:
    return {
        name: json_safe(read_input(tool, name))
        for name in SELECTOR_INPUTS
        if read_input(tool, name) is not None
    }


def select_shading_element(tool: Any, element: int, tolerance: float) -> Dict[str, Any]:
    """Select a Text+ shading element using Resolve's zero-based selector contract.

    Fusion settings serialize element 2 as SelectElement=1/Select=1 and element 3
    as SelectElement=2/Select=2. The secondary element controls are dynamic:
    selecting the element is required before its suffixed or proxy inputs can be
    instantiated and read reliably.
    """
    target = max(0, int(element) - 1)
    writes: List[Dict[str, Any]] = []
    for input_name in SELECTOR_INPUTS:
        if find_input(tool, input_name) is None and read_input(tool, input_name) is None:
            continue
        row = write_input(tool, input_name, target, tolerance)
        row["selector_input"] = input_name
        writes.append(row)
    time.sleep(0.03)
    verified = [row for row in writes if row.get("ok")]
    return {
        "ok": bool(verified) and all(bool(row.get("ok")) for row in writes),
        "element": int(element),
        "selector_value": target,
        "writes": writes,
        "readback": selector_snapshot(tool),
    }


def restore_selector(tool: Any, snapshot: Dict[str, Any], tolerance: float) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for input_name, value in (snapshot or {}).items():
        rows.append(write_input(tool, input_name, value, tolerance))
    return {"ok": all(bool(row.get("ok")) for row in rows) if rows else True, "writes": rows}


def proxy_candidates(candidates: Sequence[str], element: int) -> List[str]:
    """Return direct element IDs first, then the dynamic selected-element proxy IDs."""
    result: List[str] = []
    suffix = str(int(element))
    for candidate in candidates:
        name = str(candidate)
        if name and name.lower() not in {row.lower() for row in result}:
            result.append(name)
        if name.endswith(suffix):
            proxy = name[:-len(suffix)] + ELEMENT_PROXY_SUFFIX
            if proxy and proxy.lower() not in {row.lower() for row in result}:
                result.append(proxy)
    return result


def write_element_candidates(
    tool: Any,
    element: int,
    candidates: Sequence[str],
    expected: Any,
    tolerance: float,
    required: bool = True,
) -> Dict[str, Any]:
    selection = select_shading_element(tool, element, tolerance)
    ordered = proxy_candidates(candidates, element)
    row = write_candidates(tool, ordered, expected, tolerance, required=required)
    row["element"] = int(element)
    row["selector"] = selection
    row["direct_candidates"] = list(candidates)
    row["proxy_candidates"] = ordered

    # Force a selector round-trip. Immediate proxy readback alone is not enough:
    # switching away and back proves the value was committed to the target slot.
    alternate = 1 if int(element) != 1 else 2
    away = select_shading_element(tool, alternate, tolerance)
    back = select_shading_element(tool, element, tolerance)
    verify = read_element_candidates(tool, element, candidates, tolerance, expected)
    row["selector_roundtrip"] = {"away": away, "back": back}
    row["persistent_slot_readback"] = verify
    row["ok"] = bool(selection.get("ok") and row.get("ok") and away.get("ok") and back.get("ok") and verify.get("matched"))
    return row


def read_element_candidates(
    tool: Any,
    element: int,
    candidates: Sequence[str],
    tolerance: float,
    expected: Any = None,
) -> Dict[str, Any]:
    selection = select_shading_element(tool, element, tolerance)
    ordered = proxy_candidates(candidates, element)
    resolved = None
    value = None
    for candidate in ordered:
        current = read_input(tool, candidate)
        if current is not None:
            resolved = candidate
            value = current
            break
    matched = (
        resolved is not None
        if expected is None
        else resolved is not None and values_match(value, expected, tolerance)
    )
    return {
        "element": int(element),
        "selector": selection,
        "candidates": list(candidates),
        "proxy_candidates": ordered,
        "resolved_input": resolved,
        "value": json_safe(value),
        "matched": bool(matched),
    }


def canonical_element_property_candidates(element: int) -> Dict[str, List[str]]:
    e = int(element)
    return {
        "element_shape": [f"ElementShape{e}", f"Appearance{e}"],
        "opacity": [f"Opacity{e}", f"Alpha{e}"],
        "red": [f"Red{e}"],
        "green": [f"Green{e}"],
        "blue": [f"Blue{e}"],
        "alpha": [f"Alpha{e}"],
        "thickness": [f"Thickness{e}"],
        "outside_only": [f"OutsideOnly{e}"],
        "offset": [f"Offset{e}"],
        "softness": [f"Softness{e}", f"SoftnessX{e}"],
        "softness_x": [f"SoftnessX{e}", f"Softness{e}"],
        "softness_y": [f"SoftnessY{e}"],
    }


def read_candidates(tool: Any, candidates: Sequence[str]) -> Dict[str, Any]:
    for candidate in candidates:
        value = read_input(tool, candidate)
        if value is not None:
            return {"resolved_input": candidate, "value": json_safe(value)}
    return {"resolved_input": None, "value": None}


def all_required_ok(rows: Sequence[Dict[str, Any]]) -> bool:
    return all(bool(row.get("ok")) for row in rows if row.get("required", True))


def shading_contract(plan_item: Dict[str, Any], outline_element: int, shadow_element: int) -> Dict[str, Any]:
    effect = plan_item.get("source_effect") or {}
    outline = effect.get("outline") or {}
    shadow = effect.get("shadow") or {}
    or_, og, ob = parse_hex_color(outline.get("color"))
    sr, sg, sb = parse_hex_color(shadow.get("color"))
    return {
        "outline": {
            "requested": bool(outline.get("enabled")),
            "element": outline_element,
            "required_inputs": [
                ([f"ElementShape{outline_element}", f"Appearance{outline_element}"], 1),
                ([f"Red{outline_element}"], or_),
                ([f"Green{outline_element}"], og),
                ([f"Blue{outline_element}"], ob),
                ([f"Alpha{outline_element}"], 1.0),
                ([f"Thickness{outline_element}"], float(outline.get("thickness") or 0.0)),
            ],
            "optional_inputs": [([f"OutsideOnly{outline_element}"], 1)],
            "enable_input": ([f"Enabled{outline_element}"], 1),
            "source": outline,
        },
        "shadow": {
            "requested": bool(shadow.get("enabled")),
            "element": shadow_element,
            "required_inputs": [
                ([f"ElementShape{shadow_element}", f"Appearance{shadow_element}"], 0),
                ([f"Red{shadow_element}"], sr),
                ([f"Green{shadow_element}"], sg),
                ([f"Blue{shadow_element}"], sb),
                ([f"Opacity{shadow_element}", f"Alpha{shadow_element}"], float(shadow.get("opacity") or 0.0)),
                ([f"Offset{shadow_element}"], list(shadow.get("offset") or [0.003, 0.003])),
            ],
            "optional_inputs": [
                ([f"SoftnessX{shadow_element}", f"Softness{shadow_element}"], float(shadow.get("softness") or 0.0)),
                ([f"SoftnessY{shadow_element}"], float(shadow.get("softness") or 0.0)),
            ],
            "enable_input": ([f"Enabled{shadow_element}"], 1),
            "source": shadow,
        },
    }



def contract_is_present(tool: Any, contract: Dict[str, Any], tolerance: float) -> Tuple[bool, List[Dict[str, Any]]]:
    """Verify the real secondary element slots only.

    SelectElement/Select is retained as a UI-selection integrity check, but it is
    never treated as an API namespace switch. Resolve's scripting proxy inputs
    ending in "1" always address element 1 even when element 2 or 3 is selected.
    """
    rows: List[Dict[str, Any]] = []
    overall = True
    original_selector = selector_snapshot(tool)
    try:
        for effect_name in ("outline", "shadow"):
            effect = contract[effect_name]
            if not effect.get("requested"):
                continue
            element = int(effect["element"])
            selection = select_shading_element(tool, element, tolerance)

            for candidates, expected in effect["required_inputs"]:
                read = read_candidates(tool, candidates)
                matched = (
                    read.get("resolved_input") is not None
                    and values_match(read.get("value"), expected, tolerance)
                )
                rows.append({
                    "effect": effect_name,
                    "element": element,
                    "candidates": list(candidates),
                    "resolved_input": read.get("resolved_input"),
                    "expected": json_safe(expected),
                    "actual": read.get("value"),
                    "required": True,
                    "matched": bool(matched),
                    "selector": selection,
                    "read_mode": "direct_element_slot",
                })
                overall = overall and bool(matched)

            enable_candidates, enable_expected = effect["enable_input"]
            enable_read = read_candidates(tool, enable_candidates)
            enable_matched = (
                enable_read.get("resolved_input") is not None
                and values_match(enable_read.get("value"), enable_expected, tolerance)
            )
            rows.append({
                "effect": effect_name,
                "element": element,
                "candidates": list(enable_candidates),
                "resolved_input": enable_read.get("resolved_input"),
                "expected": json_safe(enable_expected),
                "actual": enable_read.get("value"),
                "required": True,
                "matched": bool(enable_matched),
                "selector": selection,
                "read_mode": "direct_element_slot",
            })
            overall = overall and bool(enable_matched)

            for candidates, expected in effect["optional_inputs"]:
                read = read_candidates(tool, candidates)
                matched = (
                    read.get("resolved_input") is not None
                    and values_match(read.get("value"), expected, tolerance)
                )
                rows.append({
                    "effect": effect_name,
                    "element": element,
                    "candidates": list(candidates),
                    "resolved_input": read.get("resolved_input"),
                    "expected": json_safe(expected),
                    "actual": read.get("value"),
                    "required": False,
                    "matched": bool(matched),
                    "selector": selection,
                    "read_mode": "direct_element_slot",
                })
    finally:
        restore_selector(tool, original_selector, tolerance)
    return overall, rows


def direct_slot_status(tool: Any, contract: Dict[str, Any]) -> Dict[str, Any]:
    """Report whether all required real secondary inputs have been instantiated."""
    rows: List[Dict[str, Any]] = []
    for effect_name in ("outline", "shadow"):
        effect = contract[effect_name]
        if not effect.get("requested"):
            continue
        element = int(effect["element"])
        requirements = list(effect["required_inputs"]) + [effect["enable_input"]]
        for candidates, _expected in requirements:
            resolved = None
            for candidate in candidates:
                if find_input(tool, candidate) is not None or read_input(tool, candidate) is not None:
                    resolved = candidate
                    break
            rows.append({
                "effect": effect_name,
                "element": element,
                "candidates": list(candidates),
                "resolved_input": resolved,
                "available": resolved is not None,
            })
    return {
        "ok": bool(rows) and all(row["available"] for row in rows),
        "required_slot_count": len(rows),
        "available_slot_count": sum(1 for row in rows if row["available"]),
        "slots": rows,
    }


def shading_baseline(tool: Any, elements: Sequence[int], tolerance: float = 1e-6) -> Dict[str, Any]:
    """Capture direct secondary slots plus fill and selector state.

    On a pristine Text+ title only Enabled2/Enabled3 may exist. Missing secondary
    property slots are represented as absent and rollback simply disables those
    elements. Once Resolve materializes the slots, their real values are captured.
    """
    original_selector = selector_snapshot(tool)
    result: Dict[str, Any] = {
        "schema": "textplus_direct_slot_baseline_v2",
        "selector": original_selector,
        "fill": fill_snapshot(tool, tolerance),
        "elements": {},
    }
    for element in elements:
        e = int(element)
        values: Dict[str, Any] = {}
        for key, candidates in canonical_element_property_candidates(e).items():
            read = read_candidates(tool, candidates)
            if read.get("resolved_input") is not None:
                values[key] = {
                    "candidates": list(candidates),
                    "resolved_input": read.get("resolved_input"),
                    "value": read.get("value"),
                }
        result["elements"][str(e)] = {
            "enabled": json_safe(read_input(tool, f"Enabled{e}")),
            "values": values,
        }
    result["selector_restore"] = restore_selector(tool, original_selector, tolerance)
    return result


def materialize_direct_slots(
    manager: Any,
    project: Any,
    probe_name: str,
    contract: Dict[str, Any],
    tolerance: float,
    settle_sec: float,
) -> Tuple[Dict[str, Any], Any, Any, Any, Any]:
    """Instantiate Resolve's hidden Element2/Element3 property objects safely.

    Enabling the reserved elements and saving causes Resolve to serialize and
    expose the real suffixed inputs (Red2, Thickness2, Offset3, ...). No proxy
    input ending in "1" is written during this bootstrap.
    """
    timeline = project.GetCurrentTimeline()
    v3 = scan_v3(timeline)
    item = v3.get(str(probe_name))
    comp = fusion_comp(item) if item is not None else None
    tool = textplus_tool(comp) if comp else None
    if tool is None:
        return ({"ok": False, "failure": "bootstrap_textplus_not_found"}, timeline, item, comp, tool)

    before = direct_slot_status(tool, contract)
    original_enabled = {
        str(int(contract[name]["element"])): json_safe(
            read_input(tool, f"Enabled{int(contract[name]['element'])}")
        )
        for name in ("outline", "shadow")
        if contract[name].get("requested")
    }
    result: Dict[str, Any] = {
        "ok": before.get("ok", False),
        "required": not before.get("ok", False),
        "before": before,
        "original_enabled": original_enabled,
        "enable_writes": [],
        "save_attempted": False,
        "after": before,
        "write_mode": "enable_save_reacquire_only",
    }
    if before.get("ok"):
        return result, timeline, item, comp, tool

    for name in ("outline", "shadow"):
        effect = contract[name]
        if not effect.get("requested"):
            continue
        element = int(effect["element"])
        row = write_input(tool, f"Enabled{element}", 1, tolerance)
        row["bootstrap_element"] = element
        result["enable_writes"].append(row)

    result["save_attempted"] = True
    try:
        manager.SaveProject()
    except Exception as exc:
        result["save_error"] = f"{type(exc).__name__}: {exc}"
    time.sleep(max(float(settle_sec), 0.2))

    timeline = project.GetCurrentTimeline()
    v3 = scan_v3(timeline)
    item = v3.get(str(probe_name))
    comp = fusion_comp(item) if item is not None else None
    tool = textplus_tool(comp) if comp else None
    if tool is None:
        result["ok"] = False
        result["failure"] = "bootstrap_reacquire_textplus_not_found"
        return result, timeline, item, comp, tool

    after = direct_slot_status(tool, contract)
    result["after"] = after
    result["ok"] = bool(
        all(row.get("ok") for row in result["enable_writes"])
        and after.get("ok")
    )
    if not result["ok"]:
        result["failure"] = "required_direct_slots_not_materialized"
        for element_text, enabled in original_enabled.items():
            write_input(tool, f"Enabled{int(element_text)}", enabled if enabled is not None else 0, tolerance)
        try:
            manager.SaveProject()
        except Exception:
            pass
    return result, timeline, item, comp, tool


def apply_contract(comp: Any, tool: Any, contract: Dict[str, Any], tolerance: float) -> Dict[str, Any]:
    """Write only real suffixed Element2/Element3 inputs."""
    result: Dict[str, Any] = {
        "ok": False,
        "outline": {},
        "shadow": {},
        "writes": [],
        "optional_warnings": [],
        "lock": None,
        "unlock": None,
        "selector_before": selector_snapshot(tool),
        "selector_restore": None,
        "write_mode": "direct_secondary_slots",
    }
    result["lock"] = {"attempted": True, "ok": False}
    try:
        comp.Lock()
        result["lock"]["ok"] = True
    except Exception as exc:
        result["lock"]["error"] = f"{type(exc).__name__}: {exc}"

    try:
        # Slots have already been materialized. Disable them while configuring
        # the real suffixed inputs, then enable only after required readback passes.
        for effect_name in ("outline", "shadow"):
            effect = contract[effect_name]
            disable = write_candidates(
                tool, [f"Enabled{int(effect['element'])}"], 0, tolerance, required=True
            )
            disable["stage"] = f"disable_{effect_name}"
            disable["write_mode"] = "direct_element_slot"
            result["writes"].append(disable)

        for effect_name in ("outline", "shadow"):
            effect = contract[effect_name]
            element = int(effect["element"])
            selection = select_shading_element(tool, element, tolerance)
            effect_result: Dict[str, Any] = {
                "requested": bool(effect.get("requested")),
                "element": element,
                "selection": selection,
                "required": [],
                "optional": [],
                "enable": None,
                "applied": False,
            }
            result[effect_name] = effect_result
            if not effect_result["requested"]:
                continue

            for candidates, expected in effect["required_inputs"]:
                row = write_candidates(tool, candidates, expected, tolerance, required=True)
                read = read_candidates(tool, candidates)
                row["matched_after_write"] = (
                    read.get("resolved_input") is not None
                    and values_match(read.get("value"), expected, tolerance)
                )
                row["persistent_slot_readback"] = read
                row["ok"] = bool(row.get("ok") and row["matched_after_write"])
                row["element"] = element
                row["selector"] = selection
                row["stage"] = f"configure_{effect_name}"
                row["write_mode"] = "direct_element_slot"
                effect_result["required"].append(row)
                result["writes"].append(row)

            for candidates, expected in effect["optional_inputs"]:
                row = write_candidates(tool, candidates, expected, tolerance, required=False)
                read = read_candidates(tool, candidates)
                row["matched_after_write"] = (
                    read.get("resolved_input") is not None
                    and values_match(read.get("value"), expected, tolerance)
                )
                row["persistent_slot_readback"] = read
                row["ok"] = bool(row.get("ok") and row["matched_after_write"])
                row["element"] = element
                row["selector"] = selection
                row["stage"] = f"configure_{effect_name}_optional"
                row["write_mode"] = "direct_element_slot"
                effect_result["optional"].append(row)
                result["writes"].append(row)
                if not row.get("ok"):
                    result["optional_warnings"].append(
                        f"optional_input_unavailable:{effect_name}:{'/'.join(candidates)}"
                    )

            enable_candidates, enable_expected = effect["enable_input"]
            if selection.get("ok") and all_required_ok(effect_result["required"]):
                enable = write_candidates(
                    tool, enable_candidates, enable_expected, tolerance, required=True
                )
                enable_read = read_candidates(tool, enable_candidates)
                enable["persistent_slot_readback"] = enable_read
                enable["ok"] = bool(
                    enable.get("ok")
                    and enable_read.get("resolved_input") is not None
                    and values_match(enable_read.get("value"), enable_expected, tolerance)
                )
            else:
                enable_expected = 0
                enable = write_candidates(
                    tool, [f"Enabled{element}"], 0, tolerance, required=False
                )
                enable["reason"] = "required_configuration_failed_kept_disabled"
            enable["stage"] = f"enable_{effect_name}"
            enable["write_mode"] = "direct_element_slot"
            effect_result["enable"] = enable
            result["writes"].append(enable)
            effect_result["applied"] = bool(
                selection.get("ok")
                and all_required_ok(effect_result["required"])
                and enable.get("ok")
                and enable_expected == 1
            )
    finally:
        result["selector_restore"] = restore_selector(
            tool, result.get("selector_before") or {}, tolerance
        )
        result["unlock"] = {"attempted": True, "ok": False}
        try:
            comp.Unlock()
            result["unlock"]["ok"] = True
        except Exception as exc:
            result["unlock"]["error"] = f"{type(exc).__name__}: {exc}"

    requested_ok = all(
        bool(result[name].get("applied"))
        for name in ("outline", "shadow")
        if contract[name].get("requested")
    )
    result["ok"] = bool(
        requested_ok
        and (result.get("selector_restore") or {}).get("ok", False)
    )
    return result


def restore_baseline(
    comp: Any,
    tool: Any,
    baseline: Dict[str, Any],
    elements: Sequence[int],
    tolerance: float,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "ok": True,
        "writes": [],
        "fallback_disabled": [],
        "selector_before": selector_snapshot(tool),
        "selector_restore": None,
        "baseline_schema": baseline.get("schema") if isinstance(baseline, dict) else None,
        "verification": {},
    }
    try:
        comp.Lock()
    except Exception:
        pass
    try:
        for element in elements:
            disable = write_input(tool, f"Enabled{int(element)}", 0, tolerance)
            disable["rollback_property"] = "disable_before_restore"
            result["writes"].append(disable)
            if not disable.get("ok"):
                result["ok"] = False

        schema = (baseline or {}).get("schema") if isinstance(baseline, dict) else None
        if schema in {
            "textplus_direct_slot_baseline_v2",
            "textplus_selected_element_proxy_baseline_v1",
        }:
            baseline_elements = (baseline or {}).get("elements") or {}
            for element in elements:
                e = int(element)
                element_row = baseline_elements.get(str(e)) or {}
                for key, value_row in (element_row.get("values") or {}).items():
                    candidates = (
                        value_row.get("candidates")
                        or canonical_element_property_candidates(e).get(key)
                        or []
                    )
                    # Rollback always uses the real suffixed slots. By the time a
                    # write failure can occur, Resolve has materialized them.
                    write = write_candidates(
                        tool, candidates, value_row.get("value"), tolerance, required=False
                    )
                    write["rollback_property"] = key
                    write["write_mode"] = "direct_element_slot"
                    result["writes"].append(write)
                    if not write.get("ok"):
                        result["ok"] = False

                enabled = element_row.get("enabled")
                if enabled is None:
                    enabled = 0
                    result["fallback_disabled"].append(f"Enabled{e}")
                enable_write = write_input(tool, f"Enabled{e}", enabled, tolerance)
                enable_write["rollback_property"] = "enabled"
                result["writes"].append(enable_write)
                if not enable_write.get("ok"):
                    result["ok"] = False

            fill = (baseline or {}).get("fill") or {}
            for input_name in ("Enabled1", "Red1", "Green1", "Blue1", "Alpha1"):
                if input_name not in fill:
                    continue
                row = write_input(tool, input_name, fill[input_name], tolerance)
                row["rollback_property"] = f"fill:{input_name}"
                result["writes"].append(row)
                if not row.get("ok"):
                    result["ok"] = False
        else:
            # v1.0 compatibility: restore any flat values and keep reserved
            # elements disabled when no complete baseline exists.
            for name, value in (baseline or {}).items():
                if not isinstance(name, str) or name.lower().startswith("enabled"):
                    continue
                row = write_input(tool, name, value, tolerance)
                result["writes"].append(row)
                if not row.get("ok"):
                    result["ok"] = False
            for element in elements:
                e = int(element)
                name = f"Enabled{e}"
                enabled = (baseline or {}).get(name, 0)
                row = write_input(tool, name, enabled, tolerance)
                result["writes"].append(row)
                if not row.get("ok"):
                    result["ok"] = False
                if name not in (baseline or {}):
                    result["fallback_disabled"].append(name)
    finally:
        selector_target = (
            (baseline or {}).get("selector")
            if isinstance(baseline, dict)
            else None
        ) or result.get("selector_before") or {}
        result["selector_restore"] = restore_selector(tool, selector_target, tolerance)
        if not result["selector_restore"].get("ok"):
            result["ok"] = False
        try:
            comp.Unlock()
        except Exception:
            pass

    expected_fill = (baseline or {}).get("fill") if isinstance(baseline, dict) else None
    actual_fill = fill_snapshot(tool, tolerance) if expected_fill else None
    enabled_verification = {}
    for element in elements:
        e = int(element)
        expected_enabled = (
            ((baseline or {}).get("elements") or {}).get(str(e), {}).get("enabled")
            if isinstance(baseline, dict)
            else None
        )
        if expected_enabled is None:
            expected_enabled = 0
        actual_enabled = read_input(tool, f"Enabled{e}")
        enabled_verification[str(e)] = {
            "expected": json_safe(expected_enabled),
            "actual": json_safe(actual_enabled),
            "matched": values_match(actual_enabled, expected_enabled, tolerance),
        }
    result["verification"] = {
        "fill": {
            "expected": expected_fill,
            "actual": actual_fill,
            "matched": (
                True
                if expected_fill is None
                else snapshots_match(actual_fill, expected_fill, tolerance)
            ),
        },
        "enabled": enabled_verification,
    }
    if not result["verification"]["fill"]["matched"]:
        result["ok"] = False
    if not all(row["matched"] for row in enabled_verification.values()):
        result["ok"] = False
    return result


def identity_snapshot(item: Any, tool: Any) -> Dict[str, Any]:
    return {
        "name": item_name(item),
        "start": item_start(item),
        "end": item_end(item),
        "text": str(read_input(tool, "StyledText") or ""),
        "font": str(read_input(tool, "Font") or ""),
        "style": str(read_input(tool, "Style") or ""),
    }


def fill_snapshot(tool: Any, tolerance: float = 1e-6) -> Dict[str, Any]:
    original_selector = selector_snapshot(tool)
    selection = select_shading_element(tool, 1, tolerance)
    try:
        return {
            "Enabled1": json_safe(read_input(tool, "Enabled1")),
            "Red1": json_safe(read_input(tool, "Red1")),
            "Green1": json_safe(read_input(tool, "Green1")),
            "Blue1": json_safe(read_input(tool, "Blue1")),
            "Alpha1": json_safe(read_input(tool, "Alpha1")),
            "selector_verified": bool(selection.get("ok")),
        }
    finally:
        restore_selector(tool, original_selector, tolerance)

def layout_snapshot(tool: Any) -> Dict[str, Any]:
    center_input = find_input(tool, "Center")
    size_input = find_input(tool, "Size")
    return {
        "center_at_local_zero": json_safe(read_input(tool, "Center", 0)),
        "center_modifier_connected": connected_output(center_input) is not None,
        "size_modifier_connected": connected_output(size_input) is not None,
    }


def animation_snapshot(
    tool: Any,
    targets: Sequence[Dict[str, Any]],
    tolerance: float = 1e-5,
) -> List[Dict[str, Any]]:
    """Read the live Step 3C targets using the same tolerance contract as Step 3C.

    Step 3C validates temporal Fusion values at 1e-5. The v1.1 shading probe
    accidentally tightened that contract to 1e-6 and discarded the failing
    values before writing its report. That could reject a valid persisted
    modifier because of harmless Resolve floating-point readback drift.
    """
    rows: List[Dict[str, Any]] = []
    tolerance = max(float(tolerance), 1e-5)
    for target in targets:
        input_name = str(target.get("input") or "")
        frame = int(target.get("local_frame") or 0)
        expected = target.get("expected")
        input_object = find_input(tool, input_name)
        actual = read_input(tool, input_name, frame)
        modifier_connected = connected_output(input_object) is not None
        matched = values_match(actual, expected, tolerance)

        expected_point = normalize_point(expected)
        actual_point = normalize_point(actual)
        delta: Any = None
        if expected_point is not None and actual_point is not None:
            delta = [
                abs(actual_point[0] - expected_point[0]),
                abs(actual_point[1] - expected_point[1]),
            ]
        else:
            expected_number = finite(expected)
            actual_number = finite(actual)
            if expected_number is not None and actual_number is not None:
                delta = abs(actual_number - expected_number)

        rows.append({
            "input": input_name,
            "local_frame": frame,
            "expected": json_safe(expected),
            "actual": json_safe(actual),
            "delta": json_safe(delta),
            "tolerance": tolerance,
            "input_found": input_object is not None,
            "modifier_connected": modifier_connected,
            "matched": matched,
            "present": bool(modifier_connected and matched),
            "verification_method": "connected_modifier_and_temporal_value_readback",
        })
    return rows


def protected_integrity(
    before: Dict[str, Any],
    after: Dict[str, Any],
    tolerance: float = 1e-6,
) -> Dict[str, Any]:
    failures: List[str] = []
    if before["identity"] != after["identity"]:
        failures.append("caption_identity_changed")
    if not snapshots_match(after["fill"], before["fill"], tolerance):
        failures.append("fill_shading_element_changed")
    if not snapshots_match(after["layout"], before["layout"], tolerance):
        failures.append("caption_layout_or_modifier_connection_changed")
    before_animation = before["animation"]
    after_animation = after["animation"]
    if len(before_animation) != len(after_animation):
        failures.append("animation_target_count_changed")
    else:
        for first, second in zip(before_animation, after_animation):
            if first.get("input") != second.get("input") or first.get("local_frame") != second.get("local_frame"):
                failures.append("animation_target_identity_changed")
                continue
            if not second.get("modifier_connected") or not second.get("matched"):
                failures.append(f"animation_target_changed:{second.get('input')}@{second.get('local_frame')}")
    return {"ok": not failures, "failures": failures, "before": before, "after": after}



def select_probe(plan: Dict[str, Any], cue_id: str) -> Dict[str, Any]:
    selected = [row for row in (plan.get("items") or []) if isinstance(row, dict) and row.get("probe_selected")]
    if len(selected) != 1:
        raise RuntimeError(f"Plan must contain exactly one probe item, found {len(selected)}")
    if selected[0].get("cue_id") != cue_id:
        raise RuntimeError(f"Plan probe is {selected[0].get('cue_id')}, config expects {cue_id}")
    return selected[0]


def run() -> Dict[str, Any]:
    started = time.time()
    cfg_path, config = load_config()
    plan_path = Path(config["plan_path"])
    latest_path = Path(config["latest_report_path"])
    first_path = Path(config["first_report_path"])
    idempotency_path = Path(config["idempotency_report_path"])
    state_path = Path(config["state_path"])
    status_path = Path(config["workspace_status_path"])
    log_path = Path(config["workspace_log_path"])
    expected_v3 = int(config.get("expected_v3_count") or 116)
    cue_id = str(config.get("probe_cue_id") or "sub_019")
    outline_element = int(config.get("outline_element") or 2)
    shadow_element = int(config.get("shadow_element") or 3)
    tolerance = float(config.get("value_tolerance") or 1e-6)
    animation_tolerance = max(float(config.get("animation_value_tolerance") or 1e-5), 1e-5)
    run_id = f"{int(time.time())}-{os.getpid()}"

    status = {"ok": False, "running": True, "step": "Major Step 3B.3A", "version": VERSION, "run_id": run_id, "started_at_unix": now_unix()}
    write_json(status_path, status)
    append_log(log_path, "workspace_started", status)

    report: Dict[str, Any] = {
        "ok": False,
        "step": "Major Step 3B.3A",
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

    try:
        plan = load_json(plan_path)
        if not plan.get("ok"):
            raise RuntimeError("Step 3B.3 plan has ok=false")
        if plan.get("plan_hash") != canonical_hash(plan):
            raise RuntimeError("Step 3B.3 plan hash is invalid")
        if int(plan.get("expected_v3_count") or 0) != expected_v3:
            raise RuntimeError("Step 3B.3 plan expected V3 count mismatch")
        probe = select_probe(plan, cue_id)
        contract = shading_contract(probe, outline_element, shadow_element)
        if not contract["outline"]["requested"] or not contract["shadow"]["requested"]:
            raise RuntimeError("The safety probe requires both source outline and source shadow")
        protected_targets = probe.get("protected_animation_targets") or []
        if len(protected_targets) != 2:
            raise RuntimeError("The selected animated probe must protect exactly two Step 3C keyframes")

        resolve_app = get_resolve()
        manager = resolve_app.GetProjectManager()
        project = manager.GetCurrentProject() if manager else None
        if project is None:
            raise RuntimeError("No Resolve project is open")
        timeline = project.GetCurrentTimeline()
        if timeline is None:
            raise RuntimeError("No Resolve timeline is open")

        tracks_before = scan_tracks(timeline)
        v3_before = scan_v3(timeline)
        ranges_before = v3_ranges(v3_before)
        if len(v3_before) != expected_v3:
            raise RuntimeError(f"Expected {expected_v3} V3 clips, found {len(v3_before)}")
        timeline_item = v3_before.get(str(probe.get("name")))
        if timeline_item is None:
            raise RuntimeError(f"Probe V3 item not found: {probe.get('name')}")
        comp = fusion_comp(timeline_item)
        tool = textplus_tool(comp) if comp else None
        if tool is None:
            raise RuntimeError("Probe Text+ tool not found")

        identity_before = identity_snapshot(timeline_item, tool)
        expected_identity = {
            "name": probe.get("name"),
            "start": int(probe.get("start") or 0),
            "end": int(probe.get("end") or 0),
            "text": str(probe.get("text") or ""),
            "font": str(probe.get("expected_font_family") or ""),
            "style": str(probe.get("expected_font_face") or ""),
        }
        identity_checks = {
            "name": identity_before["name"] == expected_identity["name"],
            "start": identity_before["start"] == expected_identity["start"],
            "end": identity_before["end"] == expected_identity["end"],
            "text": normalize_text(identity_before["text"]) == normalize_text(expected_identity["text"]),
            "font": normalize_token(identity_before["font"]) == normalize_token(expected_identity["font"]),
            "style": normalize_token(identity_before["style"] or "Regular") == normalize_token(expected_identity["style"] or "Regular"),
        }
        if not all(identity_checks.values()):
            raise RuntimeError(f"Probe identity/font preflight failed: {identity_checks}")

        before_protected = {
            "identity": identity_before,
            "fill": fill_snapshot(tool, tolerance),
            "layout": layout_snapshot(tool),
            "animation": animation_snapshot(tool, protected_targets, animation_tolerance),
        }
        animation_rows = before_protected["animation"]
        animation_preflight_ok = all(row.get("present") for row in animation_rows)
        if not animation_preflight_ok:
            report.update({
                "ok": False,
                "run_mode": "preflight_failed",
                "failures": ["step_3C_animation_preflight_failed"],
                "preflight": {
                    "stage": "step_3C_animation_integrity",
                    "writes_attempted": False,
                    "rollback_required": False,
                    "animation_value_tolerance": animation_tolerance,
                    "protected_target_count": len(animation_rows),
                    "present_target_count": sum(1 for row in animation_rows if row.get("present")),
                    "targets": animation_rows,
                    "diagnosis": (
                        "The live V3 Text+ item does not satisfy the persisted Step 3C "
                        "modifier/value contract. No outline or shadow inputs were written."
                    ),
                },
                "runtime_seconds": round(time.time() - started, 3),
            })
            write_json(latest_path, report)
            status.update({
                "ok": False,
                "running": False,
                "finished_at_unix": now_unix(),
                "return_code": 2,
                "run_mode": "preflight_failed",
                "report": str(latest_path),
                "failures": report["failures"],
                "preflight": report["preflight"],
            })
            write_json(status_path, status)
            append_log(log_path, "workspace_preflight_failed", status)
            return report

        baseline = shading_baseline(tool, [outline_element, shadow_element], tolerance)
        inventory_before = input_inventory(tool)
        already_correct_before, readback_before = contract_is_present(tool, contract, tolerance)

        existing_state = load_json(state_path) if state_path.is_file() else {}
        if existing_state and existing_state.get("plan_hash") not in (None, plan.get("plan_hash")):
            raise RuntimeError("Existing Step 3B.3 state belongs to a different plan hash")

        state = dict(existing_state)
        baseline_needs_upgrade = (
            not state.get("original_shading_baseline")
            or (state.get("original_shading_baseline") or {}).get("schema")
               != "textplus_direct_slot_baseline_v2"
        )
        if baseline_needs_upgrade and not state.get("first_application_completed"):
            state.update({
                "ok": False,
                "step": "Major Step 3B.3A",
                "workspace_version": VERSION,
                "plan_hash": plan.get("plan_hash"),
                "probe_cue_id": cue_id,
                "probe_name": probe.get("name"),
                "original_shading_baseline": baseline,
                "original_identity": identity_before,
                "first_application_started": True,
                "first_application_completed": False,
                "created_at_unix": now_unix(),
            })
            write_json(state_path, state)

        writes: Optional[Dict[str, Any]] = None
        bootstrap: Dict[str, Any] = {
            "ok": True,
            "required": False,
            "write_mode": "not_required_already_correct",
        }
        modified = 0
        already = 0
        if already_correct_before:
            already = 1
        else:
            bootstrap, timeline, timeline_item, comp, tool = materialize_direct_slots(
                manager,
                project,
                str(probe.get("name")),
                contract,
                tolerance,
                float(config.get("save_settle_sec") or 1.0),
            )
            if not bootstrap.get("ok") or tool is None or comp is None:
                report["failures"].append("direct_shading_slot_materialization_failed")
            else:
                writes = apply_contract(comp, tool, contract, tolerance)
                if writes.get("ok"):
                    modified = 1
                else:
                    report["failures"].append("direct_shading_input_application_failed")

        if float(config.get("readback_delay_sec") or 0.0) > 0:
            time.sleep(float(config.get("readback_delay_sec")))
        try:
            manager.SaveProject()
        except Exception:
            pass
        time.sleep(float(config.get("save_settle_sec") or 1.0))

        # Reacquire every Resolve/Fusion object. Old handles do not prove persistence.
        timeline = project.GetCurrentTimeline()
        v3_after = scan_v3(timeline)
        timeline_item_after = v3_after.get(str(probe.get("name")))
        comp_after = fusion_comp(timeline_item_after) if timeline_item_after is not None else None
        tool_after = textplus_tool(comp_after) if comp_after else None
        if tool_after is None:
            report["failures"].append("readback_textplus_not_found")
            readback_ok, readback_rows = False, []
            protected = {"ok": False, "failures": ["readback_textplus_not_found"], "before": before_protected, "after": None}
            inventory_after = None
        else:
            readback_ok, readback_rows = contract_is_present(tool_after, contract, tolerance)
            after_protected = {
                "identity": identity_snapshot(timeline_item_after, tool_after),
                "fill": fill_snapshot(tool_after, tolerance),
                "layout": layout_snapshot(tool_after),
                "animation": animation_snapshot(tool_after, protected_targets, animation_tolerance),
            }
            protected = protected_integrity(before_protected, after_protected, tolerance)
            inventory_after = input_inventory(tool_after)

        tracks_after = scan_tracks(timeline)
        ranges_after = v3_ranges(v3_after)
        track_integrity = tracks_before == tracks_after
        v3_integrity = ranges_before == ranges_after and len(v3_after) == expected_v3

        if not readback_ok:
            report["failures"].append("outline_shadow_persistent_readback_failed")
        if not protected.get("ok"):
            report["failures"].extend(protected.get("failures") or ["protected_caption_integrity_failed"])
        if not track_integrity:
            report["failures"].append("timeline_track_integrity_failed")
        if not v3_integrity:
            report["failures"].append("v3_track_integrity_failed")

        rollback = None
        rollback_performed = False
        if report["failures"] and bool(config.get("rollback_on_failure", True)) and tool_after is not None:
            rollback_performed = True
            original = state.get("original_shading_baseline") or baseline
            rollback = restore_baseline(comp_after, tool_after, original, [outline_element, shadow_element], tolerance)
            try:
                manager.SaveProject()
            except Exception:
                pass

        first_completed_before = bool(existing_state.get("first_application_completed"))
        if already_correct_before and first_completed_before:
            run_mode = "idempotent_second_run"
        elif modified == 1:
            run_mode = "first_application"
        elif already_correct_before and first_path.is_file():
            run_mode = "idempotent_second_run"
        elif already_correct_before:
            run_mode = "first_application_recovery"
            report["warnings"].append("Probe shading already existed before this run, but no completed first-run state was found.")
        else:
            run_mode = "failed_application"

        mode_path = idempotency_path if run_mode == "idempotent_second_run" else first_path
        required_readbacks = sum(1 for row in readback_rows if row.get("required"))
        verified_readbacks = sum(1 for row in readback_rows if row.get("required") and row.get("matched"))
        optional_readbacks = sum(1 for row in readback_rows if not row.get("required"))
        optional_verified = sum(1 for row in readback_rows if not row.get("required") and row.get("matched"))

        report.update({
            "ok": not report["failures"],
            "run_mode": run_mode,
            "mode_report": str(mode_path),
            "plan_hash": plan.get("plan_hash"),
            "project_name": safe_call(project, "GetName", default=None),
            "timeline_name": safe_call(timeline, "GetName", default=None),
            "summary": {
                "v3_candidate_count": len(v3_after),
                "plan_item_count": len(plan.get("items") or []),
                "probe_item_count": 1,
                "mapped_count": 1 if timeline_item_after is not None else 0,
                "modified_count": modified,
                "already_correct_count": already,
                "outline_requested_count": 1,
                "outline_verified_count": 1 if readback_ok else 0,
                "shadow_requested_count": 1,
                "shadow_verified_count": 1 if readback_ok else 0,
                "required_input_count": required_readbacks,
                "verified_required_input_count": verified_readbacks,
                "optional_input_count": optional_readbacks,
                "verified_optional_input_count": optional_verified,
                "selector_element_count": 2,
                "selector_verified_count": sum(
                    1
                    for effect_name in ("outline", "shadow")
                    if all(
                        bool((row.get("selector") or {}).get("ok"))
                        for row in readback_rows
                        if row.get("effect") == effect_name and row.get("required")
                    )
                    and any(
                        row.get("effect") == effect_name and row.get("required")
                        for row in readback_rows
                    )
                ),
                "protected_animation_target_count": len(protected_targets),
                "protected_animation_verified_count": sum(1 for row in ((protected.get("after") or {}).get("animation") or []) if row.get("modifier_connected") and row.get("matched")),
                "identity_integrity_failure_count": 1 if "caption_identity_changed" in (protected.get("failures") or []) else 0,
                "fill_integrity_failure_count": 1 if "fill_shading_element_changed" in (protected.get("failures") or []) else 0,
                "layout_integrity_failure_count": 1 if "caption_layout_or_modifier_connection_changed" in (protected.get("failures") or []) else 0,
                "animation_integrity_failure_count": 0 if all(row.get("modifier_connected") and row.get("matched") for row in ((protected.get("after") or {}).get("animation") or [])) else 1,
                "timeline_integrity_failure_count": 0 if track_integrity and v3_integrity else 1,
                "rollback_performed_count": 1 if rollback_performed else 0,
                "failed_count": 0 if not report["failures"] else 1,
            },
            "probe": {
                "cue_id": cue_id,
                "name": probe.get("name"),
                "source_effect": probe.get("source_effect"),
                "contract": contract,
                "identity_preflight": identity_checks,
                "already_correct_before": already_correct_before,
                "readback_before": readback_before,
                "baseline": baseline,
                "inventory_before": inventory_before,
                "bootstrap": bootstrap,
                "write": writes,
                "persistent_readback_ok": readback_ok,
                "persistent_readback": readback_rows,
                "inventory_after": inventory_after,
                "protected_integrity": protected,
                "rollback": rollback,
            },
            "track_integrity": {"ok": track_integrity, "before": tracks_before, "after": tracks_after},
            "v3_track_integrity": {"ok": v3_integrity, "before": ranges_before, "after": ranges_after},
            "runtime_seconds": round(time.time() - started, 3),
        })

        write_json(latest_path, report)
        write_json(mode_path, report)
        state.update({
            "ok": report["ok"],
            "last_run_mode": run_mode,
            "last_report": str(latest_path),
            "last_mode_report": str(mode_path),
            "modified_count": modified,
            "already_correct_count": already,
            "persistent_readback_ok": readback_ok,
            "protected_integrity_ok": bool(protected.get("ok")),
            "updated_at_unix": now_unix(),
        })
        if report["ok"] and run_mode in {"first_application", "first_application_recovery"}:
            state["first_application_completed"] = True
            state["first_application_report"] = str(first_path)
        if report["ok"] and run_mode == "idempotent_second_run":
            state["idempotency_completed"] = True
            state["idempotency_report"] = str(idempotency_path)
        write_json(state_path, state)

        status.update({
            "ok": report["ok"], "running": False, "finished_at_unix": now_unix(),
            "return_code": 0 if report["ok"] else 1, "run_mode": run_mode,
            "report": str(latest_path), "mode_report": str(mode_path), "summary": report["summary"],
            "failures": report["failures"], "warnings": report["warnings"],
        })
        write_json(status_path, status)
        append_log(log_path, "workspace_finished", status)
        return report
    except Exception as exc:
        report.update({
            "ok": False,
            "run_mode": "exception",
            "exception": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "runtime_seconds": round(time.time() - started, 3),
        })
        if not report.get("failures"):
            report["failures"] = ["workspace_exception"]
        write_json(latest_path, report)
        status.update({
            "ok": False, "running": False, "finished_at_unix": now_unix(), "return_code": 1,
            "report": str(latest_path), "exception": report["exception"], "traceback": report["traceback"],
        })
        write_json(status_path, status)
        append_log(log_path, "workspace_exception", status)
        return report


def main() -> None:
    report = run()
    summary = report.get("summary") or {}
    if report.get("ok"):
        show_message(
            "Video Cloner — Step 3B.3A probe complete",
            "Outline/shadow safety probe finished.\n\n"
            f"Probe cue: {report.get('probe_cue_id')}\n"
            f"Modified: {summary.get('modified_count', 0)}\n"
            f"Already correct: {summary.get('already_correct_count', 0)}\n"
            f"Required inputs verified: {summary.get('verified_required_input_count', 0)}/{summary.get('required_input_count', 0)}\n"
            f"Animation targets preserved: {summary.get('protected_animation_verified_count', 0)}/{summary.get('protected_animation_target_count', 0)}\n"
            f"Failures: {summary.get('failed_count', 0)}\n\n"
            f"Mode report:\n{report.get('mode_report')}",
            error=False,
        )
    else:
        preflight = report.get("preflight") or {}
        if report.get("run_mode") == "preflight_failed":
            headline = "The probe stopped before writing shading inputs. No rollback was required."
            details = (
                f"\n\nStep 3C targets present: "
                f"{preflight.get('present_target_count', 0)}/"
                f"{preflight.get('protected_target_count', 0)}"
            )
        elif report.get("run_mode") == "exception":
            headline = "The Workspace script raised an exception. Rollback is not assumed."
            details = f"\n\nException: {report.get('exception') or 'unknown'}"
        else:
            headline = "The probe did not pass. Check the report for rollback status."
            details = ""
        show_message(
            "Video Cloner — Step 3B.3A probe failed",
            headline
            + details
            + "\n\nFailures:\n- "
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
