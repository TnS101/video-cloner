#!/usr/bin/env python3
"""
resolve_subtitle_style_adapter.py

Video Cloner - DaVinci Resolve subtitle style adapter.

v1.2 child-process Resolve bridge
---------------------------------
This version fixes the v1.1 failure mode where the parent process could hang/crash while
importing DaVinciResolveScript / fusionscript.dll.

Main design:
- The n8n-facing parent process NEVER imports DaVinciResolveScript directly.
- The parent loads/validates style files and writes a report immediately.
- Resolve API work runs in a separate child Python process.
- The child has a hard timeout. If fusionscript.dll hangs/crashes, the parent still exits
  cleanly and writes a useful report.
- Default --never-fail true keeps n8n from failing the node; inspect the JSON report for
  the real verdict.

Architecture reality:
Native Resolve subtitle-track styling is not consistently exposed through the public
scripting API. This adapter probes the available API routes and records what works.
If native subtitle styling is inaccessible, the correct fallback is a Text+ / FCPXML
styled-title layer generator.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

VERSION = "resolve_subtitle_style_adapter_v1_2_child_process_resolve_bridge"
SCHEMA = "video_cloner_resolve_subtitle_style_adapter"
SCHEMA_VERSION = "1.2"

BOOT_LOG: Optional[Path] = None


# -----------------------------------------------------------------------------
# Boot logging / report writing
# -----------------------------------------------------------------------------


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def init_boot_log(path: Optional[str] = None, report_path: Optional[str] = None, suffix: str = "boot") -> Path:
    global BOOT_LOG
    if path:
        BOOT_LOG = Path(path)
    elif report_path:
        base = Path(report_path)
        BOOT_LOG = base.with_name(base.stem.replace("_report", "") + f"_{suffix}.log")
    else:
        temp_dir = Path(os.environ.get("TEMP", os.getcwd()))
        BOOT_LOG = temp_dir / f"video_cloner_subtitle_style_adapter_{suffix}.log"
    try:
        BOOT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(BOOT_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n[{now()}] BOOT_LOG_INIT version={VERSION} pid={os.getpid()}\n")
            f.flush()
    except Exception:
        pass
    return BOOT_LOG


def hard_log(message: str, payload: Any = None) -> None:
    path = BOOT_LOG or init_boot_log()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{now()}] {message}\n")
            if payload is not None:
                try:
                    f.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")
                except Exception:
                    f.write(str(payload) + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
    except Exception:
        pass


def write_json(path: str, data: Dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass


def safe_write_report(report_path: str, report: Dict[str, Any], phase: str) -> None:
    report["last_write_phase"] = phase
    report["updated_at_unix"] = time.time()
    try:
        write_json(report_path, report)
        hard_log("REPORT_WRITTEN", {"phase": phase, "path": report_path})
    except Exception as exc:
        hard_log("REPORT_WRITE_FAILED", {"phase": phase, "path": report_path, "error": str(exc)})


# -----------------------------------------------------------------------------
# Generic helpers
# -----------------------------------------------------------------------------


def str2bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Boolean expected, got: {value}")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(round(float(value)))
    except Exception:
        return default


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def compact_repr(value: Any, limit: int = 300) -> str:
    try:
        text = repr(value)
    except Exception:
        text = str(type(value))
    return text[:limit] + ("..." if len(text) > limit else "")


def callable_names(obj: Any, keywords: Optional[Iterable[str]] = None) -> List[str]:
    keys = [k.lower() for k in (keywords or [])]
    names: List[str] = []
    try:
        for name in dir(obj):
            if name.startswith("_"):
                continue
            if keys and not any(k in name.lower() for k in keys):
                continue
            try:
                if callable(getattr(obj, name)):
                    names.append(name)
            except Exception:
                names.append(name)
    except Exception:
        pass
    return sorted(set(names))


def hex_to_rgb01(hex_color: Any, default: Tuple[float, float, float] = (1.0, 1.0, 1.0)) -> Tuple[float, float, float]:
    if not isinstance(hex_color, str):
        return default
    value = hex_color.strip().lstrip("#")
    if len(value) != 6:
        return default
    try:
        return (
            round(int(value[0:2], 16) / 255.0, 6),
            round(int(value[2:4], 16) / 255.0, 6),
            round(int(value[4:6], 16) / 255.0, 6),
        )
    except Exception:
        return default


def rgb01_to_255(rgb: Tuple[float, float, float]) -> Tuple[int, int, int]:
    return tuple(int(round(clamp(v, 0.0, 1.0) * 255)) for v in rgb)  # type: ignore[return-value]


# -----------------------------------------------------------------------------
# Resolve scripting environment and child Resolve bridge
# -----------------------------------------------------------------------------


def configure_resolve_env() -> Dict[str, Any]:
    api_root = r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
    api_modules = os.path.join(api_root, "Modules")
    lib_path = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"

    if not os.environ.get("RESOLVE_SCRIPT_API") and os.path.exists(api_root):
        os.environ["RESOLVE_SCRIPT_API"] = api_root
    if not os.environ.get("RESOLVE_SCRIPT_LIB") and os.path.exists(lib_path):
        os.environ["RESOLVE_SCRIPT_LIB"] = lib_path
    if os.path.exists(api_modules) and api_modules not in sys.path:
        sys.path.append(api_modules)

    return {
        "RESOLVE_SCRIPT_API": os.environ.get("RESOLVE_SCRIPT_API"),
        "RESOLVE_SCRIPT_LIB": os.environ.get("RESOLVE_SCRIPT_LIB"),
        "api_root_exists": os.path.exists(api_root),
        "api_modules_exists": os.path.exists(api_modules),
        "lib_exists": os.path.exists(lib_path),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "pid": os.getpid(),
    }


def import_resolve_module_child_only() -> Any:
    env_info = configure_resolve_env()
    hard_log("CHILD_IMPORT_RESOLVE_MODULE_START", env_info)

    try:
        import DaVinciResolveScript  # type: ignore
        hard_log("CHILD_IMPORT_RESOLVE_MODULE_OK", {"method": "normal_import"})
        return DaVinciResolveScript
    except BaseException as exc:
        hard_log("CHILD_IMPORT_RESOLVE_MODULE_NORMAL_FAILED", {"type": type(exc).__name__, "error": str(exc)})

    candidates: List[Path] = []
    env_script_api = os.environ.get("RESOLVE_SCRIPT_API")
    if env_script_api:
        candidates.append(Path(env_script_api) / "Modules" / "DaVinciResolveScript.py")

    candidates.extend([
        Path(r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules\DaVinciResolveScript.py"),
        Path(r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Developer\Scripting\Modules\DaVinciResolveScript.py"),
        Path("/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/DaVinciResolveScript.py"),
        Path("/opt/resolve/Developer/Scripting/Modules/DaVinciResolveScript.py"),
    ])

    for path in candidates:
        hard_log("CHILD_IMPORT_RESOLVE_MODULE_CANDIDATE", {"path": str(path), "exists": path.exists()})
        if not path.exists():
            continue
        spec = importlib.util.spec_from_file_location("DaVinciResolveScript", str(path))
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            hard_log("CHILD_IMPORT_RESOLVE_MODULE_EXEC_START", {"path": str(path)})
            spec.loader.exec_module(module)  # type: ignore[attr-defined]
            hard_log("CHILD_IMPORT_RESOLVE_MODULE_OK", {"method": "spec_from_file", "path": str(path)})
            return module

    raise RuntimeError("Could not import DaVinciResolveScript. Check RESOLVE_SCRIPT_API / Resolve installation.")


def get_injected_resolve_handle() -> Optional[Any]:
    for name in ("resolve", "Resolve"):
        candidate = globals().get(name)
        if candidate is not None and hasattr(candidate, "GetProjectManager"):
            hard_log("CHILD_INJECTED_RESOLVE_FOUND", {"name": name, "type": type(candidate).__name__})
            return candidate
    return None


def timed_api_call(label: str, fn: Any, timeout_hint: float = 15.0) -> Any:
    # This is not thread-based on purpose. The parent process owns the hard timeout.
    # Resolve API objects sometimes dislike cross-thread calls. Child process isolation is safer.
    hard_log(f"CHILD_API_CALL_START {label}", {"timeout_hint_parent_owned": timeout_hint})
    value = fn()
    hard_log(f"CHILD_API_CALL_OK {label}", {"type": type(value).__name__, "truthy": bool(value)})
    return value


def get_resolve_child(timeout_hint: float = 15.0) -> Any:
    injected = get_injected_resolve_handle()
    if injected:
        return injected
    module = import_resolve_module_child_only()
    hard_log("CHILD_SCRIPTAPP_RESOLVE_START")
    resolve = timed_api_call("DaVinciResolveScript.scriptapp('Resolve')", lambda: module.scriptapp("Resolve"), timeout_hint)
    if not resolve:
        raise RuntimeError("Could not connect to DaVinci Resolve. Make sure Resolve is open and external scripting is enabled.")
    return resolve


def get_active_context_child(timeout_hint: float = 15.0) -> Dict[str, Any]:
    resolve = get_resolve_child(timeout_hint)
    project_manager = timed_api_call("resolve.GetProjectManager", lambda: resolve.GetProjectManager(), timeout_hint)
    if not project_manager:
        raise RuntimeError("Could not get Resolve ProjectManager.")
    project = timed_api_call("project_manager.GetCurrentProject", lambda: project_manager.GetCurrentProject(), timeout_hint)
    if not project:
        raise RuntimeError("No current Resolve project is open.")
    timeline = timed_api_call("project.GetCurrentTimeline", lambda: project.GetCurrentTimeline(), timeout_hint)
    if not timeline:
        raise RuntimeError("No active timeline is selected in the current project.")
    media_pool = timed_api_call("project.GetMediaPool", lambda: project.GetMediaPool(), timeout_hint)
    if not media_pool:
        raise RuntimeError("Could not get current MediaPool.")
    return {"resolve": resolve, "project_manager": project_manager, "project": project, "timeline": timeline, "media_pool": media_pool}


# -----------------------------------------------------------------------------
# Style report / ASS parsing
# -----------------------------------------------------------------------------


def read_ass_style(ass_path: Optional[str]) -> Dict[str, Any]:
    if not ass_path:
        return {"available": False, "reason": "no_ass_path"}
    if not os.path.exists(ass_path):
        return {"available": False, "reason": "missing_ass", "path": ass_path}
    try:
        text = Path(ass_path).read_text(encoding="utf-8-sig", errors="replace")
    except Exception as exc:
        return {"available": False, "reason": f"read_failed: {exc}", "path": ass_path}
    fmt: List[str] = []
    styles: List[Dict[str, Any]] = []
    in_styles = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower() == "[v4+ styles]":
            in_styles = True
            continue
        if stripped.startswith("[") and stripped.lower() != "[v4+ styles]":
            in_styles = False
        if not in_styles:
            continue
        if stripped.lower().startswith("format:"):
            fmt = [x.strip() for x in stripped.split(":", 1)[1].split(",")]
        elif stripped.lower().startswith("style:") and fmt:
            values = [x.strip() for x in stripped.split(":", 1)[1].split(",")]
            styles.append({fmt[i]: values[i] for i in range(min(len(fmt), len(values)))})
    return {"available": bool(styles), "styles": styles[:5], "style_count": len(styles), "path": ass_path}


def extract_style_contract(style_report: Dict[str, Any], ass_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    style = ((style_report.get("style") or {}).get("style_contract") or {}) or style_report.get("style_contract") or {}
    fill = style.get("fill") or ((style.get("colors") or {}).get("fill")) or "#ffffff"
    outline = style.get("outline") or style.get("stroke") or ((style.get("colors") or {}).get("stroke")) or "#000000"
    shadow = style.get("shadow") or ((style.get("colors") or {}).get("shadow")) or outline
    placement = style.get("placement") or {}
    anchor = style.get("anchor") or (placement.get("anchor") or {})
    typography = style.get("typography") or {}
    font_name = style.get("font_name") or typography.get("font_family")
    if not font_name or str(font_name).lower() in {"unknown", "normal_or_unknown", "unknown_or_static_from_sampling"}:
        font_name = "Arial"
    font_size = safe_int(style.get("font_size") or typography.get("font_height_px"), 60)
    outline_px = safe_int(style.get("outline_px") or ((style.get("stroke") or {}).get("width_px_estimate")), 3)
    shadow_px = safe_int(style.get("shadow_px") or ((style.get("shadow") or {}).get("blur_px_estimate")), 2)
    bold = bool(style.get("bold", str(typography.get("font_weight", "")).lower() == "bold"))
    italic = bool(style.get("italic", False))
    play_res_x = safe_int((style_report.get("style") or {}).get("play_res_x"), 1080)
    play_res_y = safe_int((style_report.get("style") or {}).get("play_res_y"), 1920)
    x_norm = safe_float(anchor.get("x"), 0.5)
    y_norm = safe_float(anchor.get("y"), 0.6875)
    pixel_x = safe_int(anchor.get("pixel_x"), int(round(x_norm * play_res_x)))
    pixel_y = safe_int(anchor.get("pixel_y"), int(round(y_norm * play_res_y)))
    return {
        "font_name": str(font_name),
        "font_size": font_size,
        "bold": bold,
        "italic": italic,
        "fill": fill,
        "fill_rgb01": hex_to_rgb01(fill),
        "fill_rgb255": rgb01_to_255(hex_to_rgb01(fill)),
        "outline": outline,
        "outline_rgb01": hex_to_rgb01(outline, (0.0, 0.0, 0.0)),
        "outline_rgb255": rgb01_to_255(hex_to_rgb01(outline, (0.0, 0.0, 0.0))),
        "shadow": shadow,
        "shadow_rgb01": hex_to_rgb01(shadow, (0.0, 0.0, 0.0)),
        "shadow_rgb255": rgb01_to_255(hex_to_rgb01(shadow, (0.0, 0.0, 0.0))),
        "outline_px": outline_px,
        "shadow_px": shadow_px,
        "anchor": {"x": round(x_norm, 5), "y": round(y_norm, 5), "pixel_x": pixel_x, "pixel_y": pixel_y},
        "play_res_x": play_res_x,
        "play_res_y": play_res_y,
        "placement": placement,
        "source_style": style,
        "ass_info": ass_info or {},
    }


# -----------------------------------------------------------------------------
# Resolve operations - executed only in child process
# -----------------------------------------------------------------------------


def try_call(obj: Any, method_name: str, *args: Any, **kwargs: Any) -> Dict[str, Any]:
    rec: Dict[str, Any] = {"method": method_name, "ok": False, "returned": None, "error": None}
    try:
        method = getattr(obj, method_name)
    except Exception as exc:
        rec["error"] = f"missing: {exc}"
        return rec
    try:
        value = method(*args, **kwargs)
        rec["ok"] = bool(value)
        rec["returned"] = compact_repr(value)
    except Exception as exc:
        rec["error"] = f"exception: {type(exc).__name__}: {exc}"
    return rec


def get_track_count(timeline: Any, track_type: str) -> int:
    try:
        return int(timeline.GetTrackCount(track_type) or 0)
    except Exception:
        return 0


def get_items_in_track(timeline: Any, track_type: str, index: int) -> List[Any]:
    try:
        items = timeline.GetItemListInTrack(track_type, index) or []
        return items if isinstance(items, list) else list(items)
    except Exception:
        return []


def ensure_subtitle_track(timeline: Any, name: str) -> Dict[str, Any]:
    before = get_track_count(timeline, "subtitle")
    rec: Dict[str, Any] = {"before": before, "after": before, "added": False, "renamed": False, "errors": []}
    if before <= 0:
        result = try_call(timeline, "AddTrack", "subtitle")
        rec["add_track_result"] = result
        after = get_track_count(timeline, "subtitle")
        rec["added"] = after > before
        rec["after"] = after
    if rec["after"] > 0:
        try:
            rec["renamed"] = bool(timeline.SetTrackName("subtitle", 1, name))
        except Exception as exc:
            rec["errors"].append(f"SetTrackName failed: {type(exc).__name__}: {exc}")
    return rec


def discover_subtitle_items(timeline: Any) -> Dict[str, Any]:
    tracks: List[Dict[str, Any]] = []
    total = 0
    sub_count = get_track_count(timeline, "subtitle")
    for i in range(1, sub_count + 1):
        items = get_items_in_track(timeline, "subtitle", i)
        previews = []
        for j, item in enumerate(items[:10], start=1):
            rec: Dict[str, Any] = {"ordinal": j, "object_repr": compact_repr(item, 120)}
            for method, key in (("GetName", "name"), ("GetStart", "start"), ("GetEnd", "end"), ("GetDuration", "duration")):
                try:
                    rec[key] = getattr(item, method)()
                except Exception:
                    rec[key] = None
            previews.append(rec)
        total += len(items)
        tracks.append({"track_index": i, "items_count": len(items), "items_preview": previews})
    return {"subtitle_track_count": sub_count, "subtitle_items_total": total, "tracks": tracks}


def attempt_import_files(media_pool: Any, timeline: Any, srt_path: Optional[str], ass_path: Optional[str]) -> Dict[str, Any]:
    out: List[Dict[str, Any]] = []
    for label, path in (("srt", srt_path), ("ass", ass_path)):
        if not path:
            continue
        item: Dict[str, Any] = {"label": label, "path": path, "exists": os.path.exists(path), "attempts": []}
        if not os.path.exists(path):
            out.append(item)
            continue
        item["attempts"].append(try_call(media_pool, "ImportMedia", [path]))
        item["attempts"].append(try_call(media_pool, "ImportMedia", [{"FilePath": path}]))
        item["attempts"].append(try_call(media_pool, "ImportTimelineFromFile", path))
        item["attempts"].append(try_call(media_pool, "ImportTimelineFromFile", path, {}))
        for name in callable_names(timeline, ["import", "subtitle", "caption"]):
            if name.lower() in {"importsubtitle", "importsubtitles", "importcaption", "importcaptions", "importintotimeline"}:
                item["attempts"].append(try_call(timeline, name, path))
        out.append(item)
    return {"attempted": True, "files": out}


def get_properties(item: Any) -> Dict[str, Any]:
    try:
        props = item.GetProperty()
        if isinstance(props, dict):
            return {str(k): props.get(k) for k in props.keys()}
    except Exception:
        pass
    return {}


def set_property_single(item: Any, key: str, value: Any) -> Dict[str, Any]:
    rec = {"key": key, "value": value, "ok": False, "error": None}
    try:
        rec["ok"] = bool(item.SetProperty(key, value))
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


def style_property_candidates(style: Dict[str, Any]) -> Dict[str, List[Tuple[str, Any]]]:
    font = style["font_name"]
    size = style["font_size"]
    fill_hex = style["fill"]
    outline_hex = style["outline"]
    shadow_hex = style["shadow"]
    fill_rgb01 = list(style["fill_rgb01"])
    outline_rgb01 = list(style["outline_rgb01"])
    shadow_rgb01 = list(style["shadow_rgb01"])
    outline_px = style["outline_px"]
    shadow_px = style["shadow_px"]
    x = style["anchor"]["x"]
    y = style["anchor"]["y"]

    return {
        "font": [("Font", font), ("FontFace", font), ("FontName", font), ("SubtitleFont", font), ("TextFont", font)],
        "size": [("Size", size), ("FontSize", size), ("SubtitleSize", size), ("TextSize", size)],
        "bold": [("Bold", style["bold"]), ("FontBold", style["bold"]), ("StyleBold", 1 if style["bold"] else 0)],
        "fill": [("Color", fill_hex), ("FontColor", fill_hex), ("TextColor", fill_hex), ("FillColor", fill_hex), ("Color", fill_rgb01), ("FontColor", fill_rgb01)],
        "outline_enabled": [("Outline", True), ("OutlineOn", True), ("Stroke", True), ("StrokeOn", True), ("UseOutline", True)],
        "outline_color": [("OutlineColor", outline_hex), ("StrokeColor", outline_hex), ("BorderColor", outline_hex), ("OutlineColor", outline_rgb01), ("StrokeColor", outline_rgb01)],
        "outline_size": [("OutlineSize", outline_px), ("StrokeWidth", outline_px), ("BorderWidth", outline_px), ("Outline", outline_px)],
        "shadow_enabled": [("Shadow", True), ("ShadowOn", True), ("UseShadow", True)],
        "shadow_color": [("ShadowColor", shadow_hex), ("ShadowColor", shadow_rgb01)],
        "shadow_size": [("ShadowSize", shadow_px), ("ShadowBlur", shadow_px), ("ShadowOffset", shadow_px)],
        "position": [("PositionX", x), ("PositionY", y), ("X", x), ("Y", y), ("Center", [x, y])],
    }


def apply_style_to_item(item: Any, style: Dict[str, Any], exhaustive: bool = False) -> Dict[str, Any]:
    before = get_properties(item)
    attempts: List[Dict[str, Any]] = []
    accepted: List[Dict[str, Any]] = []
    candidates = style_property_candidates(style)
    existing = set(before.keys())

    flat: List[Tuple[int, str, str, Any]] = []
    for group, pairs in candidates.items():
        for key, value in pairs:
            priority = 0 if key in existing else 1
            flat.append((priority, group, key, value))
    flat.sort(key=lambda x: (x[0], x[1], x[2]))

    satisfied_groups: set = set()
    for _, group, key, value in flat:
        if not exhaustive and group in satisfied_groups:
            continue
        rec = set_property_single(item, key, value)
        rec["group"] = group
        attempts.append(rec)
        if rec.get("ok"):
            accepted.append(rec)
            satisfied_groups.add(group)

    after = get_properties(item)
    try:
        name = item.GetName()
    except Exception:
        name = None
    return {
        "item_name": name,
        "before_property_keys": sorted(before.keys())[:200],
        "after_property_keys": sorted(after.keys())[:200],
        "attempts_count": len(attempts),
        "accepted_count": len(accepted),
        "accepted": accepted[:100],
        "attempts_preview": attempts[:60],
    }


def apply_style_to_subtitle_tracks(timeline: Any, style: Dict[str, Any], max_items: int = 0, exhaustive: bool = False) -> Dict[str, Any]:
    sub_count = get_track_count(timeline, "subtitle")
    results: List[Dict[str, Any]] = []
    processed = 0
    for track_idx in range(1, sub_count + 1):
        items = get_items_in_track(timeline, "subtitle", track_idx)
        for item_idx, item in enumerate(items, start=1):
            if max_items and processed >= max_items:
                break
            rec = apply_style_to_item(item, style, exhaustive=exhaustive)
            rec["track_index"] = track_idx
            rec["item_index"] = item_idx
            results.append(rec)
            processed += 1
        if max_items and processed >= max_items:
            break
    accepted_total = sum(safe_int(r.get("accepted_count"), 0) for r in results)
    return {
        "subtitle_track_count": sub_count,
        "items_processed": processed,
        "accepted_property_sets_total": accepted_total,
        "any_style_property_accepted": accepted_total > 0,
        "item_results_preview": results[:20],
        "item_results_count": len(results),
    }


# -----------------------------------------------------------------------------
# Child process execution
# -----------------------------------------------------------------------------


def run_child_probe(payload_path: str, output_path: str, boot_log_path: Optional[str]) -> int:
    init_boot_log(boot_log_path, output_path, suffix="child_boot")
    hard_log("CHILD_START", {"argv": sys.argv, "payload_path": payload_path, "output_path": output_path, "cwd": os.getcwd(), "executable": sys.executable})
    child_report: Dict[str, Any] = {
        "success": False,
        "version": VERSION,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "child_pid": os.getpid(),
        "started_at_unix": time.time(),
        "payload_path": payload_path,
        "output_path": output_path,
        "boot_log": str(BOOT_LOG) if BOOT_LOG else None,
        "errors": [],
        "warnings": [],
    }

    def child_write(phase: str) -> None:
        child_report["last_child_phase"] = phase
        child_report["updated_at_unix"] = time.time()
        try:
            write_json(output_path, child_report)
            hard_log("CHILD_RESULT_WRITTEN", {"phase": phase, "output_path": output_path})
        except Exception as exc:
            hard_log("CHILD_RESULT_WRITE_FAILED", {"phase": phase, "error": str(exc)})

    child_write("child_started")
    try:
        payload = load_json(payload_path)
        child_report["payload_loaded"] = True
        child_report["inputs"] = payload.get("inputs", {})
        child_report["resolve_env"] = configure_resolve_env()
        child_write("payload_loaded")

        style_contract = payload["style_contract"]
        flags = payload.get("flags") or {}
        resolve_timeout = safe_float(flags.get("resolve_timeout"), 15.0)

        child_write("before_resolve_connect")
        ctx = get_active_context_child(timeout_hint=resolve_timeout)
        project = ctx["project"]
        timeline = ctx["timeline"]
        media_pool = ctx["media_pool"]

        try:
            timeline_name = timeline.GetName()
        except Exception:
            timeline_name = None
        try:
            project_name = project.GetName()
        except Exception:
            project_name = None

        expected_timeline = flags.get("timeline_name")
        child_report["resolve_context"] = {
            "project_name": project_name,
            "timeline_name": timeline_name,
            "timeline_name_expected_substring": expected_timeline,
            "timeline_match_ok": (not expected_timeline or (timeline_name and str(expected_timeline).lower() in str(timeline_name).lower())),
            "timeline_methods_subtitle_related": callable_names(timeline, ["subtitle", "caption", "track", "import", "style"]),
            "media_pool_methods_import_related": callable_names(media_pool, ["import", "timeline", "media"]),
        }
        if expected_timeline and not child_report["resolve_context"]["timeline_match_ok"]:
            child_report["warnings"].append(f"Active timeline '{timeline_name}' does not match expected substring '{expected_timeline}'. Continuing anyway.")
        child_write("resolve_connected")

        if flags.get("ensure_subtitle_track", True):
            child_report["ensure_subtitle_track"] = ensure_subtitle_track(timeline, str(flags.get("track_name") or "VC_Styled_Subtitles"))
        else:
            child_report["ensure_subtitle_track"] = {"skipped": True, "reason": "disabled"}
        child_report["before_subtitle_items"] = discover_subtitle_items(timeline)
        child_write("before_import")

        inputs = payload.get("inputs") or {}
        if flags.get("attempt_import", True):
            child_report["import_attempts"] = attempt_import_files(media_pool, timeline, inputs.get("srt"), inputs.get("ass"))
        else:
            child_report["import_attempts"] = {"skipped": True, "reason": "disabled"}
        child_report["after_import_subtitle_items"] = discover_subtitle_items(timeline)
        child_write("after_import")

        if flags.get("apply_style", True):
            child_report["style_application"] = apply_style_to_subtitle_tracks(
                timeline,
                style_contract,
                max_items=max(0, safe_int(flags.get("max_items"), 0)),
                exhaustive=bool(flags.get("exhaustive_properties", False)),
            )
        else:
            child_report["style_application"] = {"skipped": True, "reason": "disabled"}
        child_report["after_style_subtitle_items"] = discover_subtitle_items(timeline)

        any_import_ok = False
        for file_item in (child_report.get("import_attempts") or {}).get("files", []) or []:
            for attempt in file_item.get("attempts", []) or []:
                if attempt.get("ok"):
                    any_import_ok = True

        style_ok = bool((child_report.get("style_application") or {}).get("any_style_property_accepted"))
        subtitle_items_found = safe_int((child_report.get("after_import_subtitle_items") or {}).get("subtitle_items_total"), 0)
        child_report["adapter_verdict"] = {
            "dry_run": False,
            "style_contract_loaded": True,
            "resolve_connected": True,
            "srt_exists": bool(inputs.get("srt") and os.path.exists(str(inputs.get("srt")))),
            "ass_exists": bool(inputs.get("ass") and os.path.exists(str(inputs.get("ass")))),
            "import_api_accepted_any_file": any_import_ok,
            "subtitle_items_found": subtitle_items_found,
            "style_api_accepted_any_property": style_ok,
            "fully_automatic_native_subtitle_style_applied": bool(style_ok),
            "next_fallback_if_false": "Generate/import styled Text+/FCPXML title layer if Resolve native subtitle properties remain inaccessible.",
        }
        child_report["success"] = True
        child_report["runtime_sec"] = round(time.time() - child_report["started_at_unix"], 4)
        child_write("complete")
        return 0

    except BaseException as exc:
        child_report["success"] = False
        child_report["errors"].append({"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()})
        child_report["adapter_verdict"] = {
            "resolve_connected": bool(child_report.get("resolve_context")),
            "fully_automatic_native_subtitle_style_applied": False,
            "failed_child_phase": child_report.get("last_child_phase"),
            "next_step": "Inspect child boot log. If failure is before resolve_connected, Resolve bridge/import is the blocker.",
        }
        child_report["runtime_sec"] = round(time.time() - child_report["started_at_unix"], 4)
        hard_log("CHILD_ERROR", child_report["errors"][-1])
        child_write("error")
        return 1


def child_paths_from_report(report_path: str) -> Dict[str, str]:
    base = Path(report_path)
    stem = base.stem
    return {
        "payload": str(base.with_name(stem + "_child_payload.json")),
        "output": str(base.with_name(stem + "_child_result.json")),
        "boot_log": str(base.with_name(stem + "_child_boot.log")),
    }


def spawn_child_probe(args: argparse.Namespace, report: Dict[str, Any], style_contract: Dict[str, Any]) -> Dict[str, Any]:
    paths = child_paths_from_report(args.report)
    payload = {
        "version": VERSION,
        "created_at_unix": time.time(),
        "inputs": {
            "style_report": args.style_report,
            "srt": args.srt,
            "ass": args.ass,
            "report": args.report,
        },
        "flags": {
            "timeline_name": args.timeline_name,
            "attempt_import": bool(args.attempt_import),
            "ensure_subtitle_track": bool(args.ensure_subtitle_track),
            "track_name": args.track_name,
            "apply_style": bool(args.apply_style),
            "max_items": int(args.max_items),
            "exhaustive_properties": bool(args.exhaustive_properties),
            "resolve_timeout": float(args.resolve_timeout),
        },
        "style_contract": style_contract,
    }
    write_json(paths["payload"], payload)

    script_path = os.path.abspath(sys.argv[0] or __file__)
    cmd = [
        sys.executable,
        script_path,
        "--child-resolve-probe", "true",
        "--child-payload", paths["payload"],
        "--child-output", paths["output"],
        "--child-boot-log", paths["boot_log"],
    ]
    timeout = max(3.0, safe_float(args.child_timeout, 0.0) or (safe_float(args.resolve_timeout, 15.0) + 10.0))

    hard_log("PARENT_CHILD_SPAWN_START", {"cmd": cmd, "timeout_seconds": timeout, "paths": paths})
    child_summary: Dict[str, Any] = {
        "mode": "child_process",
        "command": cmd,
        "timeout_seconds": timeout,
        "paths": paths,
        "started_at_unix": time.time(),
    }

    try:
        proc = subprocess.run(
            cmd,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
        child_summary.update({
            "completed": True,
            "timed_out": False,
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-4000:],
            "stderr_tail": (proc.stderr or "")[-4000:],
        })
        hard_log("PARENT_CHILD_SPAWN_COMPLETE", child_summary)
    except subprocess.TimeoutExpired as exc:
        child_summary.update({
            "completed": False,
            "timed_out": True,
            "returncode": None,
            "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else compact_repr(exc.stdout, 4000),
            "stderr_tail": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else compact_repr(exc.stderr, 4000),
            "error": f"Child process timed out after {timeout}s. This usually means Resolve bridge import/scriptapp/API call hung.",
        })
        hard_log("PARENT_CHILD_TIMEOUT", child_summary)
    except BaseException as exc:
        child_summary.update({
            "completed": False,
            "timed_out": False,
            "returncode": None,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })
        hard_log("PARENT_CHILD_SPAWN_ERROR", child_summary)

    child_result: Optional[Dict[str, Any]] = None
    if os.path.exists(paths["output"]):
        try:
            child_result = load_json(paths["output"])
            child_summary["child_result_loaded"] = True
            child_summary["child_last_phase"] = child_result.get("last_child_phase")
        except BaseException as exc:
            child_summary["child_result_loaded"] = False
            child_summary["child_result_load_error"] = f"{type(exc).__name__}: {exc}"
    else:
        child_summary["child_result_loaded"] = False
        child_summary["child_result_missing"] = True

    return {"child_process": child_summary, "child_result": child_result}


# -----------------------------------------------------------------------------
# Main parent process
# -----------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Apply/probe cloned styled subtitle contract to DaVinci Resolve timeline subtitles.")
    p.add_argument("--style-report", default=None)
    p.add_argument("--srt", default=None)
    p.add_argument("--ass", default=None)
    p.add_argument("--report", default=None)
    p.add_argument("--boot-log", default=None, help="Independent parent boot/debug log path")
    p.add_argument("--timeline-name", default=None)
    p.add_argument("--attempt-import", type=str2bool, default=True)
    p.add_argument("--ensure-subtitle-track", type=str2bool, default=True)
    p.add_argument("--track-name", default="VC_Styled_Subtitles")
    p.add_argument("--apply-style", type=str2bool, default=True)
    p.add_argument("--max-items", type=int, default=0)
    p.add_argument("--exhaustive-properties", type=str2bool, default=False)
    p.add_argument("--dry-run", type=str2bool, default=False, help="Validate files/style only. Does not connect to Resolve.")
    p.add_argument("--resolve-timeout", type=float, default=15.0, help="Resolve API hint timeout used inside child diagnostics.")
    p.add_argument("--child-timeout", type=float, default=0.0, help="Hard timeout for child Resolve bridge process. 0 = resolve-timeout + 10 seconds.")
    p.add_argument("--never-fail", type=str2bool, default=True, help="Exit 0 even on failure so n8n can inspect report.")
    p.add_argument("--bridge-mode", default="child", choices=["child"], help="Only child bridge is supported in v1.2.")

    # Internal child arguments. Do not use from n8n directly.
    p.add_argument("--child-resolve-probe", type=str2bool, default=False)
    p.add_argument("--child-payload", default=None)
    p.add_argument("--child-output", default=None)
    p.add_argument("--child-boot-log", default=None)
    return p


def stdout_json(payload: Dict[str, Any]) -> None:
    try:
        print(json.dumps(payload, ensure_ascii=False, default=str), flush=True)
    except Exception:
        print(str(payload), flush=True)


def validate_parent_args(args: argparse.Namespace) -> None:
    missing = []
    for name in ("style_report", "report"):
        if not getattr(args, name, None):
            missing.append("--" + name.replace("_", "-"))
    if missing:
        raise ValueError("Missing required arguments: " + ", ".join(missing))


def build_initial_report(args: argparse.Namespace, started: float) -> Dict[str, Any]:
    return {
        "success": False,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "started_at_unix": started,
        "boot_log": str(BOOT_LOG) if BOOT_LOG else None,
        "inputs": {
            "style_report": args.style_report,
            "srt": args.srt,
            "ass": args.ass,
            "report": args.report,
            "attempt_import": args.attempt_import,
            "apply_style": args.apply_style,
            "dry_run": args.dry_run,
            "never_fail": args.never_fail,
            "bridge_mode": args.bridge_mode,
            "child_timeout": args.child_timeout,
            "resolve_timeout": args.resolve_timeout,
        },
        "file_checks": {},
        "errors": [],
        "warnings": [],
    }


def run_parent(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    started = time.time()
    validate_parent_args(args)
    init_boot_log(args.boot_log, args.report, suffix="boot")
    hard_log("PARENT_SCRIPT_START", {"version": VERSION, "argv": sys.argv, "cwd": os.getcwd(), "executable": sys.executable, "pid": os.getpid()})

    report = build_initial_report(args, started)
    safe_write_report(args.report, report, "started")

    try:
        report["file_checks"] = {
            "style_report_exists": os.path.exists(args.style_report),
            "srt_exists": bool(args.srt and os.path.exists(args.srt)),
            "ass_exists": bool(args.ass and os.path.exists(args.ass)),
        }
        if not os.path.exists(args.style_report):
            raise FileNotFoundError(f"Style report not found: {args.style_report}")

        hard_log("PARENT_LOAD_STYLE_REPORT_START", {"path": args.style_report})
        style_report = load_json(args.style_report)
        ass_info = read_ass_style(args.ass)
        style_contract = extract_style_contract(style_report, ass_info=ass_info)
        report["style_contract_resolved"] = style_contract
        report["style_report_summary"] = {
            "compiler_version": style_report.get("version"),
            "cue_count": ((style_report.get("timing") or {}).get("cue_count")),
            "word_level_likely": ((style_report.get("timing") or {}).get("word_level_likely")),
        }
        safe_write_report(args.report, report, "style_loaded")

        if args.dry_run:
            report["success"] = True
            report["adapter_verdict"] = {
                "dry_run": True,
                "style_contract_loaded": True,
                "resolve_connected": False,
                "native_subtitle_style_attempted": False,
                "fully_automatic_native_subtitle_style_applied": False,
                "next_step": "Run with --dry-run false to probe Resolve API through child process.",
            }
            report["runtime_sec"] = round(time.time() - started, 4)
            safe_write_report(args.report, report, "dry_run_complete")
            return 0, report

        report["resolve_env_parent_only"] = configure_resolve_env()
        safe_write_report(args.report, report, "before_child_resolve_probe")

        child_bundle = spawn_child_probe(args, report, style_contract)
        report["child_process"] = child_bundle.get("child_process")
        child_result = child_bundle.get("child_result")
        if child_result:
            report["child_result_summary"] = {
                "success": child_result.get("success"),
                "last_child_phase": child_result.get("last_child_phase"),
                "errors_count": len(child_result.get("errors") or []),
                "warnings_count": len(child_result.get("warnings") or []),
                "adapter_verdict": child_result.get("adapter_verdict"),
            }
            # Merge useful child fields into top-level report for compatibility with v1.1 reports.
            for key in (
                "resolve_env", "resolve_context", "ensure_subtitle_track", "before_subtitle_items",
                "import_attempts", "after_import_subtitle_items", "style_application",
                "after_style_subtitle_items", "adapter_verdict"
            ):
                if key in child_result:
                    report[key] = child_result[key]
            if child_result.get("errors"):
                report["errors"].extend(child_result.get("errors") or [])
            if child_result.get("warnings"):
                report["warnings"].extend(child_result.get("warnings") or [])
            report["success"] = bool(child_result.get("success"))
        else:
            cp = report.get("child_process") or {}
            report["success"] = False
            report["adapter_verdict"] = {
                "dry_run": False,
                "style_contract_loaded": True,
                "resolve_connected": False,
                "child_process_completed": cp.get("completed"),
                "child_process_timed_out": cp.get("timed_out"),
                "fully_automatic_native_subtitle_style_applied": False,
                "failed_phase": "child_resolve_probe",
                "next_step": "Inspect child boot log. If it stops at CHILD_IMPORT_RESOLVE_MODULE_START, fusionscript.dll/DaVinciResolveScript import is hanging under external Python.",
            }
            if cp.get("timed_out"):
                report["errors"].append({
                    "type": "ChildProcessTimeout",
                    "message": cp.get("error") or "Child Resolve bridge process timed out.",
                    "child_boot_log": (cp.get("paths") or {}).get("boot_log"),
                })
            else:
                report["errors"].append({
                    "type": "ChildProcessNoResult",
                    "message": "Child Resolve bridge process did not produce a result JSON.",
                    "child_process": cp,
                })

        report["runtime_sec"] = round(time.time() - started, 4)
        safe_write_report(args.report, report, "complete" if report.get("success") else "complete_with_failure")
        return (0 if args.never_fail else (0 if report.get("success") else 1)), report

    except BaseException as exc:
        report["success"] = False
        report["errors"].append({"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()})
        report["adapter_verdict"] = {
            "style_contract_loaded": bool(report.get("style_contract_resolved")),
            "resolve_connected": bool(report.get("resolve_context")),
            "fully_automatic_native_subtitle_style_applied": False,
            "failed_phase": report.get("last_write_phase"),
            "next_step": "Open this report and boot_log.",
        }
        report["runtime_sec"] = round(time.time() - started, 4)
        hard_log("PARENT_SCRIPT_ERROR", report["errors"][-1])
        safe_write_report(args.report, report, "error")
        return (0 if args.never_fail else 1), report


def main() -> int:
    parser = build_arg_parser()
    try:
        args = parser.parse_args()
    except BaseException as exc:
        init_boot_log()
        hard_log("ARGPARSE_FAILED", {"error": str(exc), "argv": sys.argv, "traceback": traceback.format_exc()})
        stdout_json({"success": False, "version": VERSION, "stage": "argparse_failed", "error": str(exc)})
        return 0

    if args.child_resolve_probe:
        if not args.child_payload or not args.child_output:
            init_boot_log(args.child_boot_log, args.child_output, suffix="child_boot")
            hard_log("CHILD_ARG_ERROR", {"argv": sys.argv})
            stdout_json({"success": False, "version": VERSION, "stage": "child_arg_error", "error": "Missing --child-payload or --child-output"})
            return 2
        exit_code = run_child_probe(args.child_payload, args.child_output, args.child_boot_log)
        return int(exit_code)

    try:
        exit_code, report = run_parent(args)
    except BaseException as exc:
        init_boot_log(getattr(args, "boot_log", None), getattr(args, "report", None), suffix="boot")
        hard_log("FATAL_PARENT_RUN_ERROR", {"error": str(exc), "traceback": traceback.format_exc()})
        if getattr(args, "report", None):
            fatal_report = {
                "success": False,
                "schema": SCHEMA,
                "schema_version": SCHEMA_VERSION,
                "version": VERSION,
                "last_write_phase": "fatal_parent_run_error",
                "errors": [{"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}],
                "adapter_verdict": {"fully_automatic_native_subtitle_style_applied": False, "failed_phase": "fatal_parent_run_error"},
            }
            safe_write_report(args.report, fatal_report, "fatal_parent_run_error")
        stdout_json({"success": False, "version": VERSION, "stage": "fatal_parent_run_error", "error": str(exc)})
        return 0 if getattr(args, "never_fail", True) else 1

    verdict = report.get("adapter_verdict") or {}
    child_process = report.get("child_process") or {}
    stdout_json({
        "success": bool(report.get("success")),
        "version": VERSION,
        "report": args.report,
        "boot_log": str(BOOT_LOG) if BOOT_LOG else None,
        "last_write_phase": report.get("last_write_phase"),
        "child_timed_out": child_process.get("timed_out"),
        "child_returncode": child_process.get("returncode"),
        "resolve_connected": verdict.get("resolve_connected"),
        "subtitle_items_found": verdict.get("subtitle_items_found"),
        "style_api_accepted_any_property": verdict.get("style_api_accepted_any_property"),
        "fully_automatic_native_subtitle_style_applied": verdict.get("fully_automatic_native_subtitle_style_applied"),
        "errors_count": len(report.get("errors") or []),
    })
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
