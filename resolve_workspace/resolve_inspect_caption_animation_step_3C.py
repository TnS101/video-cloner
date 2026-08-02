#!/usr/bin/env python3
"""
Read-only Major Step 3C diagnostic.

Inspects one scale cue and one slide cue without modifying the timeline:
- sub_019 / Size
- sub_052 / Center

The report captures the Text+ input, connected output/tool, candidate
GetKeyFrames() tables, and evaluated values at the planned local frames.
"""
from __future__ import annotations

import ctypes
import json
import math
import re
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

VERSION = "resolve_inspect_caption_animation_step_3C_v1_0"
PROJECT_ROOT = Path(r"C:\Users\User\Downloads\Projects\Video Cloner")
VIDEO_ID = "DZsqH7auhjt"
DATA_ROOT = PROJECT_ROOT / "data" / VIDEO_ID
ANALYSIS_ROOT = DATA_ROOT / "analysis"
DAVINCI_ROOT = DATA_ROOT / "davinci"
PLAN_PATH = ANALYSIS_ROOT / f"{VIDEO_ID}_caption_animation_plan_step_3C.json"
SOURCE_TARGETS_PATH = ANALYSIS_ROOT / f"{VIDEO_ID}_caption_animation_step_3C_source_targets.json"
OUTPUT_PATH = DAVINCI_ROOT / f"{VIDEO_ID}_resolve_animation_step_3C_modifier_diagnostic.json"
CUES = ("sub_019", "sub_052")
V3_NAME_RE = re.compile(r"^VC_TEXTPLUS_(?P<index>\d+)_(?P<cue>sub_\d+)$", re.IGNORECASE)


def show_message(title: str, message: str, error: bool = False) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10 if error else 0x40)
    except Exception:
        print(title)
        print(message)


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


def json_safe(value: Any, depth: int = 0) -> Any:
    if depth > 7:
        return str(value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v, depth + 1) for v in value]
    try:
        return {str(k): json_safe(v, depth + 1) for k, v in dict(value).items()}
    except Exception:
        return str(value)


def get_resolve() -> Any:
    existing = globals().get("resolve")
    if existing is not None:
        return existing
    bmd_module = globals().get("bmd")
    if bmd_module is not None:
        app = bmd_module.scriptapp("Resolve")
        if app is not None:
            return app
    try:
        import DaVinciResolveScript as dvr  # type: ignore
        app = dvr.scriptapp("Resolve")
        if app is not None:
            return app
    except Exception:
        pass
    raise RuntimeError("Could not connect to DaVinci Resolve.")


def safe_call(obj: Any, method: str, *args: Any) -> Any:
    if obj is None:
        return None
    try:
        fn = getattr(obj, method)
        return fn(*args)
    except Exception:
        return None


def safe_attrs(obj: Any) -> Dict[str, Any]:
    attrs = safe_call(obj, "GetAttrs")
    return json_safe(attrs) if isinstance(attrs, dict) else {}


def safe_name(item: Any) -> str:
    try:
        return str(item.GetName() or "")
    except Exception:
        return ""


def scan_v3_items(timeline: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    count = int(safe_call(timeline, "GetTrackCount", "video") or 0)
    for track_index in range(1, count + 1):
        items = safe_call(timeline, "GetItemListInTrack", "video", track_index) or []
        for item in items:
            name = safe_name(item)
            if V3_NAME_RE.match(name):
                result[name] = item
    return result


def get_comp(item: Any) -> Any:
    comp = safe_call(item, "GetFusionCompByIndex", 1)
    if comp is not None:
        return comp
    for name in safe_call(item, "GetFusionCompNameList") or []:
        comp = safe_call(item, "GetFusionCompByName", name)
        if comp is not None:
            return comp
    return None


def get_text_tool(comp: Any) -> Any:
    tools = safe_call(comp, "GetToolList", False, "TextPlus") or {}
    if isinstance(tools, dict) and tools:
        return next(iter(tools.values()))
    tools = safe_call(comp, "GetToolList", False) or {}
    if isinstance(tools, dict):
        for tool in tools.values():
            if str(safe_attrs(tool).get("TOOLS_RegID") or "") == "TextPlus":
                return tool
    return None


def find_input(tool: Any, input_name: str) -> Any:
    value = safe_call(tool, "FindInput", input_name)
    if value is not None:
        return value
    try:
        value = getattr(tool, input_name)
        if value is not None:
            return value
    except Exception:
        pass
    inputs = safe_call(tool, "GetInputList") or {}
    if isinstance(inputs, dict):
        for input_object in inputs.values():
            attrs = safe_attrs(input_object)
            if attrs.get("INPS_ID") == input_name or attrs.get("INPS_Name") == input_name:
                return input_object
    return None


def connected_output(input_object: Any) -> Any:
    return safe_call(input_object, "GetConnectedOutput")


def output_tool(output: Any) -> Any:
    for method in ("GetTool", "GetOwner"):
        tool = safe_call(output, method)
        if tool is not None:
            return tool
    return None


def read_input(tool: Any, input_name: str, frame: int) -> Any:
    value = safe_call(tool, "GetInput", input_name, frame)
    if value is not None:
        return json_safe(value)
    input_object = find_input(tool, input_name)
    if input_object is not None:
        try:
            return json_safe(input_object[frame])
        except Exception:
            pass
    return None


def method_probe(obj: Any) -> List[str]:
    try:
        names = dir(obj)
    except Exception:
        return []
    wanted = ("key", "connect", "input", "output", "tool", "modifier", "attr")
    return sorted(name for name in names if any(part in name.lower() for part in wanted))[:200]


def keyframe_probe(tool: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "attrs": safe_attrs(tool),
        "methods": method_probe(tool),
    }
    for method in ("GetKeyFrames", "GetKeyframes"):
        try:
            fn = getattr(tool, method)
            result[method] = json_safe(fn())
        except Exception as exc:
            result[method] = {"error": f"{type(exc).__name__}: {exc}"}
    return result


def all_tool_keyframe_probes(comp: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    tools = safe_call(comp, "GetToolList", False) or {}
    if not isinstance(tools, dict):
        return rows
    for key, tool in tools.items():
        attrs = safe_attrs(tool)
        reg_id = str(attrs.get("TOOLS_RegID") or "")
        name = str(attrs.get("TOOLS_Name") or key)
        if reg_id in {"BezierSpline", "Path", "PolyPath"} or "spline" in reg_id.lower() or "path" in reg_id.lower():
            rows.append({
                "list_key": str(key),
                "name": name,
                "reg_id": reg_id,
                "probe": keyframe_probe(tool),
            })
    return rows


def source_items() -> Dict[str, Dict[str, Any]]:
    if SOURCE_TARGETS_PATH.exists():
        payload = load_json(SOURCE_TARGETS_PATH)
        rows = payload.get("items") or []
        return {
            str(row.get("cue_id") or ""): row
            for row in rows
            if isinstance(row, dict)
        }
    plan = load_json(PLAN_PATH)
    rows = plan.get("items") or []
    return {
        str(row.get("cue_id") or ""): row
        for row in rows
        if isinstance(row, dict)
    }


def planned_frames(row: Dict[str, Any]) -> List[int]:
    frames: List[int] = []
    for target in row.get("targets") or []:
        if isinstance(target, dict):
            try:
                frames.append(int(target.get("local_frame", target.get("frame"))))
            except Exception:
                pass
    animation = row.get("animation") or {}
    if isinstance(animation, dict):
        for keyframe in animation.get("keyframes") or []:
            if isinstance(keyframe, dict):
                try:
                    frames.append(int(keyframe.get("frame")))
                except Exception:
                    pass
    return sorted(set(frames))


def run() -> Dict[str, Any]:
    resolve_app = get_resolve()
    project_manager = resolve_app.GetProjectManager()
    project = project_manager.GetCurrentProject()
    if project is None:
        raise RuntimeError("No Resolve project is open.")
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise RuntimeError("No Resolve timeline is open.")

    v3 = scan_v3_items(timeline)
    plan_rows = source_items()
    results: List[Dict[str, Any]] = []

    for cue in CUES:
        source = plan_rows.get(cue) or {}
        name = str(source.get("name") or "")
        if not name:
            name = next((n for n in v3 if n.lower().endswith("_" + cue.lower())), "")
        item = v3.get(name)
        input_name = "Size" if cue == "sub_019" else "Center"
        row: Dict[str, Any] = {
            "cue_id": cue,
            "name": name,
            "input": input_name,
            "timeline_item_found": item is not None,
            "planned_frames": planned_frames(source),
        }
        if item is None:
            row["failure"] = "timeline_item_not_found"
            results.append(row)
            continue

        comp = get_comp(item)
        tool = get_text_tool(comp) if comp is not None else None
        input_object = find_input(tool, input_name) if tool is not None else None
        output = connected_output(input_object)
        modifier_tool = output_tool(output)

        row.update({
            "text_tool_attrs": safe_attrs(tool),
            "input_attrs": safe_attrs(input_object),
            "connected": output is not None,
            "connected_output_attrs": safe_attrs(output),
            "connected_output_methods": method_probe(output),
            "connected_modifier_tool_found": modifier_tool is not None,
            "connected_modifier": keyframe_probe(modifier_tool) if modifier_tool is not None else None,
            "candidate_modifier_tools": all_tool_keyframe_probes(comp),
            "evaluated_values": {
                str(frame): read_input(tool, input_name, frame)
                for frame in planned_frames(source)
            },
        })
        results.append(row)

    report = {
        "ok": all(row.get("timeline_item_found") and row.get("connected") for row in results),
        "step": "Major Step 3C modifier diagnostic",
        "version": VERSION,
        "plan": str(PLAN_PATH),
        "source_targets": str(SOURCE_TARGETS_PATH),
        "output": str(OUTPUT_PATH),
        "items": results,
    }
    write_json(OUTPUT_PATH, report)
    return report


def main() -> None:
    try:
        report = run()
        show_message(
            "Video Cloner — Step 3C diagnostic",
            (
                f"Diagnostic finished.\n\n"
                f"Connected targets: "
                f"{sum(1 for row in report['items'] if row.get('connected'))}/"
                f"{len(report['items'])}\n\n"
                f"Report:\n{OUTPUT_PATH}"
            ),
            error=not report["ok"],
        )
    except Exception as exc:
        failure = {
            "ok": False,
            "step": "Major Step 3C modifier diagnostic",
            "version": VERSION,
            "exception": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        try:
            write_json(OUTPUT_PATH, failure)
        except Exception:
            pass
        show_message(
            "Video Cloner — Step 3C diagnostic failed",
            f"{type(exc).__name__}: {exc}\n\nReport:\n{OUTPUT_PATH}",
            error=True,
        )


main()
