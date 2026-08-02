#!/usr/bin/env python3
"""Video Cloner — Major Step 3B.3B full V3 outline/shadow rollout.

This Resolve Workspace script promotes the verified Step 3B.3A direct-slot
contract to all V3 Text+ captions whose source metadata requests outline or
shadow. It requires the accepted sub_019 probe to already be present, applies
112 remaining captions, leaves three detector-disabled captions untouched,
preserves all 116 caption identities/fill/layout values and all 16 Step 3C
animation targets, archives first/idempotency reports, and rolls the full batch
back to the accepted-probe baseline if any required check fails.

Known visual debt: V3 fill-color fidelity is intentionally not corrected here.
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

VERSION = "resolve_caption_outline_shadow_step_3B_3B_v1_1_singleton_progress"
DEFAULT_PROJECT_ROOT = r"C:\Users\User\Downloads\Projects\Video Cloner"
DEFAULT_VIDEO_ID = "DZsqH7auhjt"
DEFAULT_CONFIG_NAME = "resolve_caption_outline_shadow_full_step_3B_3_config.json"
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
        "plan_path": str(analysis / f"{video_id}_caption_outline_shadow_full_plan_step_3B_3B.json"),
        "latest_report_path": str(davinci / f"{video_id}_resolve_outline_shadow_full_step_3B_3B_report.json"),
        "first_report_path": str(davinci / f"{video_id}_resolve_outline_shadow_full_step_3B_3B_first_application_report.json"),
        "idempotency_report_path": str(davinci / f"{video_id}_resolve_outline_shadow_full_step_3B_3B_idempotency_report.json"),
        "state_path": str(davinci / f"{video_id}_resolve_outline_shadow_full_step_3B_3B_state.json"),
        "workspace_status_path": str(davinci / f"{video_id}_resolve_outline_shadow_full_step_3B_3B_workspace_status.json"),
        "workspace_log_path": str(davinci / f"{video_id}_resolve_outline_shadow_full_step_3B_3B_workspace.log"),
        "workspace_lock_path": str(davinci / f"{video_id}_resolve_outline_shadow_full_step_3B_3B_workspace.lock"),
        "progress_every_items": 5,
        "expected_v3_count": 116,
        "expected_rollout_target_count": 113,
        "accepted_probe_cue_id": "sub_019",
        "outline_element": 2,
        "shadow_element": 3,
        "readback_delay_sec": 0.10,
        "save_settle_sec": 1.5,
        "value_tolerance": 1e-6,
        "animation_value_tolerance": 1e-5,
        "rollback_on_failure": True,
        "show_completion_message": True,
        "known_visual_debt": "V3 fill-color fidelity is not corrected in Step 3B.3B.",
    }

def config_path() -> Path:
    environment = os.environ.get("VC_STEP_3B3B_CONFIG")
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


def acquire_workspace_lock(path: Path, run_id: str) -> Dict[str, Any]:
    """Acquire a cross-process lock. Never auto-remove it while Resolve may still be running."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": VERSION,
        "run_id": run_id,
        "pid": os.getpid(),
        "started_at_unix": now_unix(),
    }
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        existing: Dict[str, Any] = {}
        try:
            existing = load_json(path)
        except Exception:
            existing = {"unreadable": True}
        return {"ok": False, "path": str(path), "existing": existing}
    except Exception as exc:
        return {"ok": False, "path": str(path), "error": f"{type(exc).__name__}: {exc}"}
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except Exception:
        try:
            path.unlink()
        except Exception:
            pass
        raise
    return {"ok": True, "path": str(path), "payload": payload}


def release_workspace_lock(path: Path, run_id: str) -> Dict[str, Any]:
    result = {"ok": True, "path": str(path), "removed": False}
    try:
        if not path.exists():
            return result
        existing = load_json(path)
        if str(existing.get("run_id") or "") != str(run_id):
            result.update({"ok": False, "reason": "lock_owned_by_different_run", "existing": existing})
            return result
        path.unlink()
        result["removed"] = True
    except Exception as exc:
        result.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return result


def update_workspace_progress(
    status_path: Path,
    log_path: Path,
    status: Dict[str, Any],
    stage: str,
    current: Optional[int] = None,
    total: Optional[int] = None,
    item_name_value: Optional[str] = None,
    message: Optional[str] = None,
) -> None:
    status["stage"] = str(stage)
    status["updated_at_unix"] = now_unix()
    started = finite(status.get("started_at_unix"))
    if started is not None:
        status["elapsed_seconds"] = round(max(0.0, time.time() - started), 3)
    progress: Dict[str, Any] = {}
    if current is not None:
        progress["current"] = int(current)
    if total is not None:
        progress["total"] = int(total)
    if current is not None and total:
        progress["percent"] = round(100.0 * int(current) / int(total), 1)
    if item_name_value:
        progress["item"] = str(item_name_value)
    if message:
        progress["message"] = str(message)
    status["progress"] = progress
    write_json(status_path, status)
    append_log(log_path, "workspace_progress", {
        "run_id": status.get("run_id"),
        "stage": stage,
        "progress": progress,
        "elapsed_seconds": status.get("elapsed_seconds"),
    })


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
    time.sleep(0.005)
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
            if not effect.get("requested"):
                continue
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



def expected_identity(plan_item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": str(plan_item.get("name") or ""),
        "start": int(plan_item.get("start") or 0),
        "end": int(plan_item.get("end") or 0),
        "text": str(plan_item.get("text") or ""),
        "font": str(plan_item.get("expected_font_family") or ""),
        "style": str(plan_item.get("expected_font_face") or ""),
    }


def identity_checks(actual: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, bool]:
    return {
        "name": actual.get("name") == expected.get("name"),
        "start": actual.get("start") == expected.get("start"),
        "end": actual.get("end") == expected.get("end"),
        "text": normalize_text(actual.get("text")) == normalize_text(expected.get("text")),
        "font": normalize_token(actual.get("font")) == normalize_token(expected.get("font")),
        "style": normalize_token(actual.get("style") or "Regular") == normalize_token(expected.get("style") or "Regular"),
    }


def capture_protected(tool: Any, item: Any, plan_item: Dict[str, Any], tolerance: float, animation_tolerance: float) -> Dict[str, Any]:
    return {
        "identity": identity_snapshot(item, tool),
        "fill": fill_snapshot(tool, tolerance),
        "layout": layout_snapshot(tool),
        "animation": animation_snapshot(tool, plan_item.get("protected_animation_targets") or [], animation_tolerance),
    }


def stable_shading_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema": snapshot.get("schema"),
        "selector": snapshot.get("selector"),
        "fill": snapshot.get("fill"),
        "elements": snapshot.get("elements"),
    }


def effect_rows_verified(rows: Sequence[Dict[str, Any]], effect_name: str) -> bool:
    required = [row for row in rows if row.get("effect") == effect_name and row.get("required")]
    return bool(required) and all(row.get("matched") for row in required)


def selector_effect_verified(rows: Sequence[Dict[str, Any]], effect_name: str) -> bool:
    required = [row for row in rows if row.get("effect") == effect_name and row.get("required")]
    return bool(required) and all(bool((row.get("selector") or {}).get("ok")) for row in required)


def compact_write_result(result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {"ok": False, "missing": True}
    writes = result.get("writes") or []
    return {
        "ok": bool(result.get("ok")),
        "write_mode": result.get("write_mode"),
        "write_count": len(writes),
        "successful_write_count": sum(1 for row in writes if row.get("ok")),
        "failed_writes": [
            {
                "stage": row.get("stage"),
                "candidates": row.get("candidates"),
                "resolved_input": row.get("resolved_input"),
                "expected": row.get("expected"),
                "actual": row.get("actual"),
            }
            for row in writes if not row.get("ok") and row.get("required", True)
        ],
        "optional_warnings": list(result.get("optional_warnings") or []),
    }


def save_and_settle(manager: Any, settle_sec: float) -> Dict[str, Any]:
    result: Dict[str, Any] = {"attempted": True, "ok": True}
    try:
        returned = manager.SaveProject()
        result["returned"] = json_safe(returned)
    except Exception as exc:
        result["ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
    time.sleep(max(float(settle_sec), 0.2))
    return result


def reacquire_entry(project: Any, name: str) -> Tuple[Any, Any, Any, Any]:
    timeline = project.GetCurrentTimeline()
    v3 = scan_v3(timeline)
    item = v3.get(str(name))
    comp = fusion_comp(item) if item is not None else None
    tool = textplus_tool(comp) if comp else None
    return timeline, item, comp, tool


def bootstrap_batch(
    manager: Any,
    project: Any,
    entries: Sequence[Dict[str, Any]],
    tolerance: float,
    settle_sec: float,
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "ok": True,
        "required_item_count": 0,
        "enable_write_count": 0,
        "enable_write_failure_count": 0,
        "items": [],
        "save": None,
    }
    for entry_index, entry in enumerate(entries, start=1):
        name = str(entry["plan_item"].get("name") or "")
        tool = entry.get("tool")
        contract = entry["contract"]
        before = direct_slot_status(tool, contract)
        row: Dict[str, Any] = {
            "name": name,
            "cue_id": entry["plan_item"].get("cue_id"),
            "before": before,
            "required": not before.get("ok"),
            "enable_writes": [],
        }
        if row["required"]:
            result["required_item_count"] += 1
            for effect_name in ("outline", "shadow"):
                effect = contract[effect_name]
                if not effect.get("requested"):
                    continue
                element = int(effect["element"])
                write = write_input(tool, f"Enabled{element}", 1, tolerance)
                row["enable_writes"].append({
                    "element": element,
                    "ok": bool(write.get("ok")),
                    "actual": write.get("actual"),
                })
                result["enable_write_count"] += 1
                if not write.get("ok"):
                    result["enable_write_failure_count"] += 1
                    result["ok"] = False
        result["items"].append(row)
        if callable(progress_callback):
            progress_callback(entry_index, len(entries), name)

    if result["required_item_count"]:
        result["save"] = save_and_settle(manager, settle_sec)
        if not result["save"].get("ok"):
            result["ok"] = False

    after_by_name: Dict[str, Dict[str, Any]] = {}
    for row, entry in zip(result["items"], entries):
        name = str(entry["plan_item"].get("name") or "")
        _timeline, item, comp, tool = reacquire_entry(project, name)
        after = direct_slot_status(tool, entry["contract"]) if tool is not None else {
            "ok": False,
            "failure": "reacquire_textplus_not_found",
        }
        row["after"] = after
        row["ok"] = bool((not row["required"] or all(w["ok"] for w in row["enable_writes"])) and after.get("ok"))
        if not row["ok"]:
            result["ok"] = False
        after_by_name[name] = {"item": item, "comp": comp, "tool": tool}
    result["reacquired"] = after_by_name
    return result


def rollback_batch(
    manager: Any,
    project: Any,
    baselines: Dict[str, Any],
    elements: Sequence[int],
    tolerance: float,
    settle_sec: float,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"attempted": True, "ok": True, "item_count": 0, "failed_items": [], "items": []}
    for name, baseline in baselines.items():
        _timeline, item, comp, tool = reacquire_entry(project, name)
        if item is None or comp is None or tool is None:
            result["ok"] = False
            result["failed_items"].append({"name": name, "failure": "reacquire_failed"})
            continue
        restored = restore_baseline(comp, tool, baseline, elements, tolerance)
        result["item_count"] += 1
        result["items"].append({"name": name, "ok": bool(restored.get("ok"))})
        if not restored.get("ok"):
            result["ok"] = False
            result["failed_items"].append({"name": name, "failure": "restore_baseline_failed"})
    result["save"] = save_and_settle(manager, settle_sec)
    if not result["save"].get("ok"):
        result["ok"] = False
    return result


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
    lock_path = Path(config.get("workspace_lock_path") or status_path.with_suffix(".lock"))
    expected_v3 = int(config.get("expected_v3_count") or 116)
    expected_targets = int(config.get("expected_rollout_target_count") or 113)
    accepted_probe_cue = str(config.get("accepted_probe_cue_id") or "sub_019")
    outline_element = int(config.get("outline_element") or 2)
    shadow_element = int(config.get("shadow_element") or 3)
    tolerance = float(config.get("value_tolerance") or 1e-6)
    animation_tolerance = max(float(config.get("animation_value_tolerance") or 1e-5), 1e-5)
    settle_sec = float(config.get("save_settle_sec") or 1.5)
    run_id = f"{int(time.time())}-{os.getpid()}"
    lock = acquire_workspace_lock(lock_path, run_id)
    if not lock.get("ok"):
        return {
            "ok": False,
            "step": "Major Step 3B.3B",
            "workspace_version": VERSION,
            "run_mode": "already_running",
            "failures": ["workspace_already_running"],
            "workspace_lock": lock,
            "latest_report": str(latest_path),
        }

    status = {"ok": False, "running": True, "step": "Major Step 3B.3B", "version": VERSION, "run_id": run_id, "started_at_unix": now_unix()}
    write_json(status_path, status)
    append_log(log_path, "workspace_started", status)
    update_workspace_progress(status_path, log_path, status, "starting", 0, expected_v3, message="Full rollout started. Do not launch it again.")
    show_message(
        "Video Cloner — Step 3B.3B started",
        "Full V3 rollout started.\n\nDo NOT run the Workspace script again while it is processing.\nThe 113-caption batch can take several minutes.\n\nUse run_monitor_DZsqH7auhjt_STEP_3B_3B.bat to see live progress.",
        error=False,
    )

    report: Dict[str, Any] = {
        "ok": False,
        "step": "Major Step 3B.3B",
        "workspace_version": VERSION,
        "config": str(cfg_path),
        "plan": str(plan_path),
        "latest_report": str(latest_path),
        "first_application_report": str(first_path),
        "idempotency_report": str(idempotency_path),
        "state": str(state_path),
        "accepted_probe_cue_id": accepted_probe_cue,
        "known_visual_debt": config.get("known_visual_debt"),
        "failures": [],
        "warnings": [
            "Step 3B.3B preserves the current V3 fill color. The known white-vs-dark-gray fill mismatch is intentionally deferred."
        ],
    }

    try:
        plan = load_json(plan_path)
        if not plan.get("ok"):
            raise RuntimeError("Step 3B.3B plan has ok=false")
        if plan.get("plan_hash") != canonical_hash(plan):
            raise RuntimeError("Step 3B.3B plan hash is invalid")
        if int(plan.get("expected_v3_count") or 0) != expected_v3:
            raise RuntimeError("Step 3B.3B plan expected V3 count mismatch")

        plan_items = [row for row in (plan.get("items") or []) if isinstance(row, dict)]
        target_items = [row for row in plan_items if row.get("rollout_selected")]
        disabled_items = [row for row in plan_items if not row.get("rollout_selected")]
        if len(plan_items) != expected_v3:
            raise RuntimeError(f"Plan must contain {expected_v3} items, found {len(plan_items)}")
        if len(target_items) != expected_targets:
            raise RuntimeError(f"Plan must contain {expected_targets} rollout targets, found {len(target_items)}")
        if len(disabled_items) != expected_v3 - expected_targets:
            raise RuntimeError("Plan disabled-item count mismatch")
        update_workspace_progress(status_path, log_path, status, "plan_validated", 0, expected_v3)

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
        update_workspace_progress(status_path, log_path, status, "v3_scan_complete", expected_v3, expected_v3)

        preflight_rows: List[Dict[str, Any]] = []
        preflight_by_name: Dict[str, Dict[str, Any]] = {}
        target_entries: List[Dict[str, Any]] = []
        disabled_baselines: Dict[str, Any] = {}
        preflight_failures: List[str] = []
        animation_target_count = 0
        animation_present_count = 0

        for preflight_index, plan_item in enumerate(plan_items, start=1):
            name = str(plan_item.get("name") or "")
            item = v3_before.get(name)
            comp = fusion_comp(item) if item is not None else None
            tool = textplus_tool(comp) if comp else None
            if item is None or comp is None or tool is None:
                preflight_failures.append(f"map_or_textplus_missing:{name}")
                preflight_rows.append({"name": name, "ok": False, "failure": "map_or_textplus_missing"})
                continue
            actual_identity = identity_snapshot(item, tool)
            checks = identity_checks(actual_identity, expected_identity(plan_item))
            protected = capture_protected(tool, item, plan_item, tolerance, animation_tolerance)
            animation_rows = protected["animation"]
            animation_target_count += len(animation_rows)
            animation_present_count += sum(1 for row in animation_rows if row.get("present"))
            identity_ok = all(checks.values())
            animation_ok = all(row.get("present") for row in animation_rows)
            row = {
                "name": name,
                "cue_id": plan_item.get("cue_id"),
                "rollout_selected": bool(plan_item.get("rollout_selected")),
                "identity_checks": checks,
                "animation_target_count": len(animation_rows),
                "animation_present_count": sum(1 for target in animation_rows if target.get("present")),
                "ok": bool(identity_ok and animation_ok),
            }
            preflight_rows.append(row)
            preflight_by_name[name] = protected
            if not identity_ok:
                preflight_failures.append(f"identity_preflight_failed:{name}")
            if not animation_ok:
                preflight_failures.append(f"animation_preflight_failed:{name}")
            if plan_item.get("rollout_selected"):
                contract = shading_contract(plan_item, outline_element, shadow_element)
                target_entries.append({
                    "plan_item": plan_item,
                    "item": item,
                    "comp": comp,
                    "tool": tool,
                    "contract": contract,
                })
            else:
                disabled_baselines[name] = stable_shading_snapshot(shading_baseline(tool, [outline_element, shadow_element], tolerance))
            if preflight_index == 1 or preflight_index % max(int(config.get("progress_every_items") or 5), 1) == 0 or preflight_index == len(plan_items):
                update_workspace_progress(status_path, log_path, status, "preflight", preflight_index, len(plan_items), name)

        if preflight_failures:
            report.update({
                "run_mode": "preflight_failed",
                "failures": ["full_rollout_preflight_failed"],
                "preflight": {
                    "writes_attempted": False,
                    "rollback_required": False,
                    "item_count": len(preflight_rows),
                    "identity_failure_count": sum(1 for row in preflight_rows if not all((row.get("identity_checks") or {}).values())),
                    "animation_target_count": animation_target_count,
                    "animation_present_count": animation_present_count,
                    "failures": preflight_failures,
                    "items": preflight_rows,
                },
                "runtime_seconds": round(time.time() - started, 3),
            })
            write_json(latest_path, report)
            status.update({"ok": False, "running": False, "finished_at_unix": now_unix(), "return_code": 2, "run_mode": "preflight_failed", "report": str(latest_path), "failures": report["failures"]})
            write_json(status_path, status)
            append_log(log_path, "workspace_preflight_failed", status)
            release_workspace_lock(lock_path, run_id)
            return report

        # The accepted Step 3B.3A probe is the required rollout baseline.
        accepted_probe_entries = [entry for entry in target_entries if str(entry["plan_item"].get("cue_id")) == accepted_probe_cue]
        if len(accepted_probe_entries) != 1:
            raise RuntimeError("Accepted probe cue is missing or duplicated in the rollout plan")
        accepted_present, accepted_readback = contract_is_present(
            accepted_probe_entries[0]["tool"], accepted_probe_entries[0]["contract"], tolerance
        )
        if not accepted_present:
            report.update({
                "run_mode": "preflight_failed",
                "failures": ["accepted_step_3B_3A_probe_not_present"],
                "preflight": {
                    "writes_attempted": False,
                    "rollback_required": False,
                    "accepted_probe_cue_id": accepted_probe_cue,
                    "accepted_probe_persistent_readback": accepted_readback,
                    "diagnosis": "Open the timeline that passed the Step 3B.3A probe and idempotency validation.",
                },
                "runtime_seconds": round(time.time() - started, 3),
            })
            write_json(latest_path, report)
            status.update({"ok": False, "running": False, "finished_at_unix": now_unix(), "return_code": 2, "run_mode": "preflight_failed", "report": str(latest_path), "failures": report["failures"]})
            write_json(status_path, status)
            append_log(log_path, "workspace_preflight_failed", status)
            release_workspace_lock(lock_path, run_id)
            return report

        existing_state = load_json(state_path) if state_path.is_file() else {}
        if existing_state and existing_state.get("plan_hash") not in (None, plan.get("plan_hash")):
            raise RuntimeError("Existing Step 3B.3B state belongs to a different plan hash")

        already_before: Dict[str, bool] = {}
        readback_before: Dict[str, Any] = {}
        original_baselines: Dict[str, Any] = {}
        for baseline_index, entry in enumerate(target_entries, start=1):
            name = str(entry["plan_item"].get("name") or "")
            present, rows = contract_is_present(entry["tool"], entry["contract"], tolerance)
            already_before[name] = bool(present)
            readback_before[name] = rows
            original_baselines[name] = shading_baseline(entry["tool"], [outline_element, shadow_element], tolerance)
            if baseline_index == 1 or baseline_index % max(int(config.get("progress_every_items") or 5), 1) == 0 or baseline_index == len(target_entries):
                update_workspace_progress(status_path, log_path, status, "capture_baselines", baseline_index, len(target_entries), name)

        first_completed_before = bool(existing_state.get("first_application_completed"))
        if not existing_state and sum(1 for value in already_before.values() if value) != 1:
            raise RuntimeError(
                "First full-rollout run requires exactly one already-correct target: the accepted sub_019 probe"
            )

        state = dict(existing_state)
        if not state.get("original_shading_baselines"):
            state.update({
                "ok": False,
                "step": "Major Step 3B.3B",
                "workspace_version": VERSION,
                "plan_hash": plan.get("plan_hash"),
                "accepted_probe_cue_id": accepted_probe_cue,
                "original_shading_baselines": original_baselines,
                "first_application_started": True,
                "first_application_completed": False,
                "created_at_unix": now_unix(),
            })
            write_json(state_path, state)

        need_apply = [entry for entry in target_entries if not already_before[str(entry["plan_item"].get("name") or "")]]
        update_workspace_progress(status_path, log_path, status, "materialize_direct_slots", 0, len(need_apply))
        bootstrap = bootstrap_batch(
            manager,
            project,
            need_apply,
            tolerance,
            settle_sec,
            progress_callback=lambda current, total, name: update_workspace_progress(
                status_path, log_path, status, "materialize_direct_slots", current, total, name
            ) if current == 1 or current % max(int(config.get("progress_every_items") or 5), 1) == 0 or current == total else None,
        )
        if not bootstrap.get("ok"):
            report["failures"].append("batch_direct_slot_materialization_failed")

        update_workspace_progress(status_path, log_path, status, "materialization_complete", len(need_apply), len(need_apply))

        # Refresh all target references after bootstrap save/reacquisition.
        refreshed_entries: List[Dict[str, Any]] = []
        for entry in target_entries:
            name = str(entry["plan_item"].get("name") or "")
            timeline, item, comp, tool = reacquire_entry(project, name)
            refreshed_entries.append({**entry, "item": item, "comp": comp, "tool": tool})
        target_entries = refreshed_entries

        writes_by_name: Dict[str, Any] = {}
        if not report["failures"]:
            write_total = len(target_entries)
            for write_index, entry in enumerate(target_entries, start=1):
                name = str(entry["plan_item"].get("name") or "")
                if already_before[name]:
                    continue
                if entry.get("tool") is None or entry.get("comp") is None:
                    writes_by_name[name] = {"ok": False, "failure": "reacquire_failed_before_write"}
                    report["failures"].append("batch_application_write_failed")
                    continue
                write_result = apply_contract(entry["comp"], entry["tool"], entry["contract"], tolerance)
                writes_by_name[name] = write_result
                if not write_result.get("ok"):
                    report["failures"].append("batch_application_write_failed")
                if write_index == 1 or write_index % max(int(config.get("progress_every_items") or 5), 1) == 0 or write_index == write_total:
                    update_workspace_progress(status_path, log_path, status, "apply_outline_shadow", write_index, write_total, name)

        save_after_write = None
        if writes_by_name:
            update_workspace_progress(status_path, log_path, status, "save_after_write", len(writes_by_name), len(writes_by_name))
            save_after_write = save_and_settle(manager, settle_sec)
            if not save_after_write.get("ok"):
                report["failures"].append("project_save_after_batch_write_failed")

        # Persistent readback and all-caption protection after save/reacquisition.
        timeline_after = project.GetCurrentTimeline()
        tracks_after = scan_tracks(timeline_after)
        v3_after = scan_v3(timeline_after)
        ranges_after = v3_ranges(v3_after)
        item_reports: List[Dict[str, Any]] = []
        all_readback_rows: List[Dict[str, Any]] = []
        outline_verified = 0
        shadow_verified = 0
        selector_verified = 0
        persistent_item_count = 0
        modified_count = 0
        already_count = sum(1 for value in already_before.values() if value)
        protected_verified_count = 0
        protected_failure_items: List[Dict[str, Any]] = []
        animation_verified_count = 0
        disabled_untouched_count = 0
        disabled_changed: List[str] = []

        target_by_name = {str(entry["plan_item"].get("name") or ""): entry for entry in target_entries}
        plan_by_name = {str(row.get("name") or ""): row for row in plan_items}

        verify_total = len(plan_by_name)
        for verify_index, (name, plan_item) in enumerate(plan_by_name.items(), start=1):
            item = v3_after.get(name)
            comp = fusion_comp(item) if item is not None else None
            tool = textplus_tool(comp) if comp else None
            if item is None or tool is None:
                protected_failure_items.append({"name": name, "failures": ["post_save_map_or_textplus_missing"]})
                continue
            after_protected = capture_protected(tool, item, plan_item, tolerance, animation_tolerance)
            integrity = protected_integrity(preflight_by_name[name], after_protected, tolerance)
            if integrity.get("ok"):
                protected_verified_count += 1
            else:
                protected_failure_items.append({"name": name, "cue_id": plan_item.get("cue_id"), "failures": integrity.get("failures")})
            animation_verified_count += sum(1 for row in after_protected["animation"] if row.get("present"))

            if plan_item.get("rollout_selected"):
                entry = target_by_name[name]
                persistent, rows = contract_is_present(tool, entry["contract"], tolerance)
                all_readback_rows.extend(rows)
                if persistent:
                    persistent_item_count += 1
                if effect_rows_verified(rows, "outline"):
                    outline_verified += 1
                if effect_rows_verified(rows, "shadow"):
                    shadow_verified += 1
                selector_verified += int(selector_effect_verified(rows, "outline"))
                selector_verified += int(selector_effect_verified(rows, "shadow"))
                if not already_before[name] and persistent and bool((writes_by_name.get(name) or {}).get("ok")):
                    modified_count += 1
                item_reports.append({
                    "name": name,
                    "cue_id": plan_item.get("cue_id"),
                    "style_profile_id": plan_item.get("style_profile_id"),
                    "already_correct_before": already_before[name],
                    "modified": bool(not already_before[name] and persistent and (writes_by_name.get(name) or {}).get("ok")),
                    "persistent_readback_ok": persistent,
                    "required_input_count": sum(1 for row in rows if row.get("required")),
                    "verified_required_input_count": sum(1 for row in rows if row.get("required") and row.get("matched")),
                    "optional_input_count": sum(1 for row in rows if not row.get("required")),
                    "verified_optional_input_count": sum(1 for row in rows if not row.get("required") and row.get("matched")),
                    "write": compact_write_result(writes_by_name.get(name)) if not already_before[name] else {"ok": True, "write_mode": "not_required_already_correct"},
                    "protected_integrity_ok": bool(integrity.get("ok")),
                    "protected_failures": integrity.get("failures") or [],
                })
            else:
                current_disabled = stable_shading_snapshot(shading_baseline(tool, [outline_element, shadow_element], tolerance))
                unchanged = snapshots_match(current_disabled, disabled_baselines[name], tolerance)
                if unchanged:
                    disabled_untouched_count += 1
                else:
                    disabled_changed.append(name)
            if verify_index == 1 or verify_index % max(int(config.get("progress_every_items") or 5), 1) == 0 or verify_index == verify_total:
                update_workspace_progress(status_path, log_path, status, "persistent_verification", verify_index, verify_total, name)

        target_count = len(target_items)
        outline_requested = sum(1 for row in target_items if (row.get("source_effect") or {}).get("outline", {}).get("enabled"))
        shadow_requested = sum(1 for row in target_items if (row.get("source_effect") or {}).get("shadow", {}).get("enabled"))
        required_count = sum(1 for row in all_readback_rows if row.get("required"))
        verified_required = sum(1 for row in all_readback_rows if row.get("required") and row.get("matched"))
        optional_count = sum(1 for row in all_readback_rows if not row.get("required"))
        verified_optional = sum(1 for row in all_readback_rows if not row.get("required") and row.get("matched"))
        track_integrity = tracks_before == tracks_after
        v3_integrity = ranges_before == ranges_after and len(v3_after) == expected_v3

        if persistent_item_count != target_count:
            report["failures"].append("full_rollout_persistent_readback_failed")
        if outline_verified != outline_requested:
            report["failures"].append("outline_rollout_incomplete")
        if shadow_verified != shadow_requested:
            report["failures"].append("shadow_rollout_incomplete")
        if verified_required != required_count:
            report["failures"].append("required_input_readback_incomplete")
        if verified_optional != optional_count:
            report["failures"].append("optional_input_readback_incomplete")
        if protected_verified_count != expected_v3:
            report["failures"].append("caption_protected_integrity_failed")
        if animation_verified_count != animation_target_count:
            report["failures"].append("step_3C_animation_integrity_failed")
        if disabled_untouched_count != len(disabled_items):
            report["failures"].append("disabled_captions_changed")
        if not track_integrity or not v3_integrity:
            report["failures"].append("timeline_integrity_failed")
        if writes_by_name and modified_count + already_count != target_count:
            report["failures"].append("modified_already_count_mismatch")

        # Deduplicate high-level failures while preserving order.
        report["failures"] = list(dict.fromkeys(report["failures"]))

        rollback = None
        rollback_performed = False
        if report["failures"] and bool(config.get("rollback_on_failure", True)):
            update_workspace_progress(status_path, log_path, status, "rollback", 0, len(original_baselines))
            rollback_performed = True
            rollback = rollback_batch(
                manager,
                project,
                state.get("original_shading_baselines") or original_baselines,
                [outline_element, shadow_element],
                tolerance,
                settle_sec,
            )
            if not rollback.get("ok"):
                report["failures"].append("batch_rollback_failed")

        if not report["failures"]:
            if modified_count > 0:
                run_mode = "first_application"
            elif already_count == target_count and first_completed_before:
                run_mode = "idempotent_second_run"
            elif already_count == target_count and first_path.is_file():
                run_mode = "idempotent_second_run"
            else:
                run_mode = "first_application_recovery"
                report["warnings"].append("Full rollout already existed, but completed first-run state was not found.")
        else:
            run_mode = "failed_application"

        mode_path = idempotency_path if run_mode == "idempotent_second_run" else first_path
        summary = {
            "v3_candidate_count": len(v3_after),
            "plan_item_count": len(plan_items),
            "rollout_target_count": target_count,
            "disabled_plan_count": len(disabled_items),
            "mapped_count": len(v3_after),
            "modified_count": modified_count,
            "already_correct_count": already_count,
            "accepted_probe_already_correct_count": 1 if already_before.get(str(accepted_probe_entries[0]["plan_item"].get("name") or "")) else 0,
            "outline_requested_count": outline_requested,
            "outline_verified_count": outline_verified,
            "shadow_requested_count": shadow_requested,
            "shadow_verified_count": shadow_verified,
            "required_input_count": required_count,
            "verified_required_input_count": verified_required,
            "optional_input_count": optional_count,
            "verified_optional_input_count": verified_optional,
            "selector_element_count": outline_requested + shadow_requested,
            "selector_verified_count": selector_verified,
            "protected_caption_count": expected_v3,
            "protected_caption_verified_count": protected_verified_count,
            "protected_animation_target_count": animation_target_count,
            "protected_animation_verified_count": animation_verified_count,
            "disabled_untouched_count": disabled_untouched_count,
            "identity_integrity_failure_count": sum(1 for row in protected_failure_items if "caption_identity_changed" in (row.get("failures") or [])),
            "fill_integrity_failure_count": sum(1 for row in protected_failure_items if "fill_shading_element_changed" in (row.get("failures") or [])),
            "layout_integrity_failure_count": sum(1 for row in protected_failure_items if "caption_layout_or_modifier_connection_changed" in (row.get("failures") or [])),
            "animation_integrity_failure_count": animation_target_count - animation_verified_count,
            "timeline_integrity_failure_count": 0 if track_integrity and v3_integrity else 1,
            "rollback_performed_count": 1 if rollback_performed else 0,
            "failed_item_count": sum(
                1
                for row in item_reports
                if not row.get("persistent_readback_ok")
                or not row.get("protected_integrity_ok")
                or not (row.get("write") or {}).get("ok")
            ),
            "failed_count": 0 if not report["failures"] else 1,
        }

        report.update({
            "ok": not report["failures"],
            "run_mode": run_mode,
            "mode_report": str(mode_path),
            "plan_hash": plan.get("plan_hash"),
            "project_name": safe_call(project, "GetName", default=None),
            "timeline_name": safe_call(project.GetCurrentTimeline(), "GetName", default=None),
            "summary": summary,
            "preflight": {
                "ok": True,
                "item_count": len(preflight_rows),
                "animation_target_count": animation_target_count,
                "animation_present_count": animation_present_count,
                "accepted_probe_present": accepted_present,
            },
            "bootstrap": {
                key: value for key, value in bootstrap.items() if key != "reacquired"
            },
            "save_after_write": save_after_write,
            "items": item_reports,
            "protected_failures": protected_failure_items,
            "disabled_items": {
                "expected_count": len(disabled_items),
                "untouched_count": disabled_untouched_count,
                "changed_names": disabled_changed,
            },
            "track_integrity": {"ok": track_integrity, "before": tracks_before, "after": tracks_after},
            "v3_track_integrity": {"ok": v3_integrity, "before": ranges_before, "after": ranges_after},
            "rollback": rollback,
            "runtime_seconds": round(time.time() - started, 3),
        })

        write_json(latest_path, report)
        write_json(mode_path, report)
        state.update({
            "ok": report["ok"],
            "last_run_mode": run_mode,
            "last_report": str(latest_path),
            "last_mode_report": str(mode_path),
            "modified_count": modified_count,
            "already_correct_count": already_count,
            "persistent_item_count": persistent_item_count,
            "protected_caption_verified_count": protected_verified_count,
            "protected_animation_verified_count": animation_verified_count,
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
            "ok": report["ok"],
            "running": False,
            "finished_at_unix": now_unix(),
            "return_code": 0 if report["ok"] else 1,
            "run_mode": run_mode,
            "report": str(latest_path),
            "mode_report": str(mode_path),
            "summary": summary,
            "failures": report["failures"],
            "warnings": report["warnings"],
        })
        write_json(status_path, status)
        append_log(log_path, "workspace_finished", status)
        release_workspace_lock(lock_path, run_id)
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
            "ok": False,
            "running": False,
            "finished_at_unix": now_unix(),
            "return_code": 1,
            "run_mode": "exception",
            "report": str(latest_path),
            "exception": report["exception"],
            "traceback": report["traceback"],
        })
        write_json(status_path, status)
        append_log(log_path, "workspace_exception", status)
        release_workspace_lock(lock_path, run_id)
        return report


def main() -> None:
    report = run()
    summary = report.get("summary") or {}
    if report.get("ok"):
        show_message(
            "Video Cloner — Step 3B.3B full rollout complete",
            "Full V3 outline/shadow rollout finished.\n\n"
            f"V3 clips: {summary.get('v3_candidate_count', 0)}\n"
            f"Rollout targets: {summary.get('rollout_target_count', 0)}\n"
            f"Modified: {summary.get('modified_count', 0)}\n"
            f"Already correct: {summary.get('already_correct_count', 0)}\n"
            f"Outline verified: {summary.get('outline_verified_count', 0)}/{summary.get('outline_requested_count', 0)}\n"
            f"Shadow verified: {summary.get('shadow_verified_count', 0)}/{summary.get('shadow_requested_count', 0)}\n"
            f"Step 3C targets preserved: {summary.get('protected_animation_verified_count', 0)}/{summary.get('protected_animation_target_count', 0)}\n"
            f"Failures: {summary.get('failed_count', 0)}\n\n"
            "Known debt: current V3 fill color is preserved and is not corrected in this step.\n\n"
            f"Mode report:\n{report.get('mode_report')}",
            error=False,
        )
    else:
        preflight = report.get("preflight") or {}
        if report.get("run_mode") == "already_running":
            lock = report.get("workspace_lock") or {}
            existing = lock.get("existing") or {}
            show_message(
                "Video Cloner — Step 3B.3B already running",
                "A Step 3B.3B rollout is already active.\n\nDo not start it again.\nWait for it to finish or fully close Resolve before using the stale-run reset BAT.\n\n"
                f"Active run: {existing.get('run_id') or 'unknown'}\n"
                f"Started: {existing.get('started_at_unix') or 'unknown'}\n"
                f"Lock: {lock.get('path') or 'unknown'}",
                error=True,
            )
            return
        if report.get("run_mode") == "preflight_failed":
            headline = "The full rollout stopped before writing. No rollback was required."
            details = f"\n\nAccepted probe present: {preflight.get('accepted_probe_present', False)}"
        elif report.get("run_mode") == "exception":
            headline = "The full-rollout Workspace script raised an exception."
            details = f"\n\nException: {report.get('exception') or 'unknown'}"
        else:
            headline = "The full rollout did not pass. Check rollback status in the report."
            details = ""
        show_message(
            "Video Cloner — Step 3B.3B full rollout failed",
            headline + details + "\n\nFailures:\n- "
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
