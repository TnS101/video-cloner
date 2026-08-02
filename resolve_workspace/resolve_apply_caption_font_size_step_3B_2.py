#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import re
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

VERSION = "resolve_caption_font_size_step_3B_2_v1_0_workspace_autorun"
DEFAULT_PROJECT_ROOT = r"C:\Users\User\Downloads\Projects\Video Cloner"
DEFAULT_VIDEO_ID = "DZsqH7auhjt"
DEFAULT_CONFIG_NAME = "resolve_caption_font_size_step_3B_2_config.json"
V3_ITEM_RE = re.compile(r"^VC_TEXTPLUS_(?P<index>\d+)_(?P<cue>.+)$", re.IGNORECASE)


def now_unix() -> float:
    return round(time.time(), 6)


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
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    try:
        return str(value)
    except Exception:
        return repr(value)


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm_token(value: Any) -> str:
    return "".join(ch.lower() for ch in norm_text(value) if ch.isalnum())


def finite(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        number = float(value)
    except Exception:
        return default
    return number if math.isfinite(number) else default


def floats_equal(a: Any, b: Any, tolerance: float) -> bool:
    left, right = finite(a), finite(b)
    return left is not None and right is not None and abs(left - right) <= tolerance


def values_equal(expected: Any, actual: Any, tolerance: float = 1e-7) -> bool:
    if isinstance(expected, str) or isinstance(actual, str):
        return norm_token(expected) == norm_token(actual)
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) <= tolerance
    if isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
        return len(expected) == len(actual) and all(values_equal(a, b, tolerance) for a, b in zip(expected, actual))
    if isinstance(expected, dict) and isinstance(actual, dict):
        return set(expected) == set(actual) and all(values_equal(expected[k], actual[k], tolerance) for k in expected)
    return json_safe(expected) == json_safe(actual)


def default_runtime_config() -> Dict[str, Any]:
    project_root = Path(os.environ.get("VC_PROJECT_ROOT", DEFAULT_PROJECT_ROOT))
    video_id = os.environ.get("VC_VIDEO_ID", DEFAULT_VIDEO_ID)
    analysis_dir = project_root / "data" / video_id / "analysis"
    davinci_dir = project_root / "data" / video_id / "davinci"
    return {
        "video_id": video_id,
        "size_plan_path": str(analysis_dir / f"{video_id}_caption_font_size_plan_step_3B_2.json"),
        "output_report_path": str(davinci_dir / f"{video_id}_resolve_font_size_step_3B_2_report.json"),
        "workspace_status_path": str(davinci_dir / f"{video_id}_resolve_font_size_step_3B_2_workspace_status.json"),
        "workspace_launch_log_path": str(davinci_dir / f"{video_id}_resolve_font_size_step_3B_2_workspace.log"),
        "v3_track": 3,
        "v3_track_name": "VC_TEXTPLUS_V3",
        "expected_v3_count": 116,
        "size_tolerance": 1e-7,
        "baseline_tolerance": 1e-6,
        "readback_delay_sec": 0.03,
        "reject_size_keyframes": True,
        "rollback_on_item_failure": True,
        "show_completion_message": True,
        "dry_run": False,
    }


def resolve_config_path() -> Path:
    env_path = os.environ.get("VC_STEP_3B2_CONFIG")
    if env_path:
        return Path(env_path).expanduser().resolve()
    root = Path(os.environ.get("VC_PROJECT_ROOT", DEFAULT_PROJECT_ROOT))
    video_id = os.environ.get("VC_VIDEO_ID", DEFAULT_VIDEO_ID)
    candidates = [root / "data" / video_id / "davinci" / DEFAULT_CONFIG_NAME]
    script_file = globals().get("__file__")
    if script_file:
        try:
            candidates.append(Path(str(script_file)).resolve().with_name(DEFAULT_CONFIG_NAME))
        except Exception:
            pass
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def load_runtime_config(path: Path) -> Dict[str, Any]:
    config = default_runtime_config()
    if path.is_file():
        config.update(load_json(path))
    return config


def append_log(path: Path, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"timestamp_unix": now_unix(), "event": event, "version": VERSION, "module_name": globals().get("__name__"), "script_path": globals().get("__file__")}
        if payload:
            row.update(json_safe(payload))
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def show_message(title: str, message: str, is_error: bool = False) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, str(message), str(title), 0x10 if is_error else 0x40)
    except Exception:
        pass


def get_resolve() -> Any:
    try:
        import DaVinciResolveScript as dvr_script  # type: ignore
        resolve = dvr_script.scriptapp("Resolve")
        if resolve is not None:
            return resolve
    except Exception:
        pass
    bmd_obj = globals().get("bmd")
    if bmd_obj is not None:
        resolve = safe_call(bmd_obj, "scriptapp", "Resolve")
        if resolve is not None:
            return resolve
    raise RuntimeError("Resolve API unavailable. Run from Workspace -> Scripts.")


def timeline_item_name(item: Any) -> str:
    name = safe_call(item, "GetName", default=None)
    if not name:
        props = safe_call(item, "GetProperty", default={}) or {}
        if isinstance(props, dict):
            name = props.get("Name") or props.get("Clip Name")
    return norm_text(name)


def timeline_item_start(item: Any) -> int:
    try:
        return int(round(float(safe_call(item, "GetStart", default=0) or 0)))
    except Exception:
        return 0


def timeline_item_end(item: Any) -> int:
    try:
        return int(round(float(safe_call(item, "GetEnd", default=0) or 0)))
    except Exception:
        return 0


def get_track_items(timeline: Any, track_type: str, index: int) -> List[Any]:
    items = safe_call(timeline, "GetItemListInTrack", track_type, int(index), default=[]) or []
    if isinstance(items, dict):
        items = list(items.values())
    return list(items)


def track_name(timeline: Any, track_type: str, index: int) -> str:
    return norm_text(safe_call(timeline, "GetTrackName", track_type, int(index), default=""))


def item_record(item: Any) -> Dict[str, Any]:
    start, end = timeline_item_start(item), timeline_item_end(item)
    return {"name": timeline_item_name(item), "start": start, "end": end, "duration": max(0, end - start)}


def snapshot_track(timeline: Any, track_type: str, index: int) -> List[Dict[str, Any]]:
    return [item_record(item) for item in get_track_items(timeline, track_type, index)]


def get_fusion_comps(item: Any) -> List[Any]:
    comps = []
    count = safe_call(item, "GetFusionCompCount", default=0) or 0
    try:
        count = int(count)
    except Exception:
        count = 0
    for index in range(1, count + 1):
        comp = safe_call(item, "GetFusionCompByIndex", index, default=None)
        if comp is not None:
            comps.append(comp)
    if not comps:
        comp = safe_call(item, "GetFusionCompByIndex", 1, default=None)
        if comp is not None:
            comps.append(comp)
    return comps


def tool_regid(tool: Any) -> str:
    attrs = safe_call(tool, "GetAttrs", default={}) or {}
    return norm_text(attrs.get("TOOLS_RegID") or attrs.get("TOOLST_RegID")) if isinstance(attrs, dict) else ""


def find_textplus_tool(item: Any) -> Tuple[Optional[Any], Dict[str, Any]]:
    diagnostics = {"fusion_comp_count": 0, "tools_seen": [], "matched": False}
    for comp in get_fusion_comps(item):
        diagnostics["fusion_comp_count"] += 1
        tools = safe_call(comp, "GetToolList", False, "TextPlus", default=None)
        if not tools:
            tools = safe_call(comp, "GetToolList", False, default={}) or {}
        if isinstance(tools, dict):
            tools = list(tools.values())
        for tool in list(tools or []):
            regid = tool_regid(tool)
            attrs = safe_call(tool, "GetAttrs", default={}) or {}
            name = norm_text(attrs.get("TOOLS_Name")) if isinstance(attrs, dict) else ""
            diagnostics["tools_seen"].append({"name": name, "regid": regid})
            if regid.lower() in {"textplus", "text3d"} or "textplus" in regid.lower():
                diagnostics["matched"] = True
                return tool, diagnostics
    return None, diagnostics


def get_input_value(tool: Any, name: str) -> Any:
    value = safe_call(tool, "GetInput", name, default=None)
    if value is not None:
        return value
    input_obj = getattr(tool, name, None)
    if input_obj is not None:
        try:
            return input_obj[0]
        except Exception:
            pass
    return None


def input_keyframes(tool: Any, name: str) -> Any:
    input_obj = getattr(tool, name, None)
    if input_obj is None:
        return None
    value = safe_call(input_obj, "GetKeyFrames", default=None)
    if value is None:
        value = safe_call(input_obj, "GetKeyFrames", True, default=None)
    return json_safe(value)


def keyframes_empty(value: Any) -> bool:
    return value in (None, {}, [])


def snapshot_inputs(tool: Any, names: Sequence[str]) -> Dict[str, Any]:
    return {name: {"value": json_safe(get_input_value(tool, name)), "keyframes": input_keyframes(tool, name)} for name in names}


def set_input_static(tool: Any, name: str, value: Any) -> Dict[str, Any]:
    attempts = []
    ok = False
    try:
        result = tool.SetInput(name, value)
        attempts.append({"method": "SetInput", "result": json_safe(result)})
        ok = result is not False
    except Exception as exc:
        attempts.append({"method": "SetInput", "error": f"{type(exc).__name__}: {exc}"})
    if not ok:
        try:
            setattr(tool, name, value)
            attempts.append({"method": "setattr", "result": True})
            ok = True
        except Exception as exc:
            attempts.append({"method": "setattr", "error": f"{type(exc).__name__}: {exc}"})
    return {"ok": bool(ok), "attempts": attempts}


def core_track_snapshot(timeline: Any, v3_track: int) -> Dict[str, Any]:
    payload = {
        "video_1": snapshot_track(timeline, "video", 1),
        "audio_1": snapshot_track(timeline, "audio", 1),
        "video_3": snapshot_track(timeline, "video", v3_track),
    }
    video_count = safe_call(timeline, "GetTrackCount", "video", default=0) or 0
    try:
        video_count = int(video_count)
    except Exception:
        video_count = 0
    if video_count >= 4:
        payload["video_4"] = snapshot_track(timeline, "video", 4)
    return payload


def run() -> int:
    config_path = resolve_config_path()
    config = load_runtime_config(config_path)
    plan_path = Path(str(config["size_plan_path"]))
    report_path = Path(str(config["output_report_path"]))
    status_path = Path(str(config["workspace_status_path"]))
    log_path = Path(str(config["workspace_launch_log_path"]))
    launch_id = f"step3b2_{int(time.time() * 1000)}"
    append_log(log_path, "workspace_script_started", {"launch_id": launch_id, "config_path": str(config_path), "plan_path": str(plan_path), "report_path": str(report_path)})
    write_json(status_path, {"ok": False, "running": True, "step": "Major Step 3B.2", "version": VERSION, "launch_id": launch_id, "started_at_unix": now_unix(), "report_path": str(report_path)})

    started = time.time()
    failures: List[str] = []
    warnings: List[str] = []
    report: Dict[str, Any] = {
        "ok": False,
        "step": "Major Step 3B.2",
        "version": VERSION,
        "created_at_unix": now_unix(),
        "config_path": str(config_path),
        "size_plan_path": str(plan_path),
        "expected_v3_count": int(config.get("expected_v3_count") or 116),
    }

    try:
        plan = load_json(plan_path)
        if not plan.get("ok"):
            raise RuntimeError("Size calibration plan is not valid.")
        expected = int(config.get("expected_v3_count") or 116)
        plan_items = [row for row in (plan.get("items") or []) if isinstance(row, dict)]
        plan_by_name = {norm_text(row.get("name")): row for row in plan_items}
        resolve = get_resolve()
        pm = safe_call(resolve, "GetProjectManager", default=None)
        project = safe_call(pm, "GetCurrentProject", default=None)
        timeline = safe_call(project, "GetCurrentTimeline", default=None)
        if project is None or timeline is None:
            raise RuntimeError("No active Resolve project/timeline.")

        v3_track = int(config.get("v3_track") or 3)
        items = [item for item in get_track_items(timeline, "video", v3_track) if V3_ITEM_RE.match(timeline_item_name(item))]
        items.sort(key=lambda item: (timeline_item_start(item), timeline_item_name(item)))
        before_tracks = core_track_snapshot(timeline, v3_track)
        report.update({
            "project_name": norm_text(safe_call(project, "GetName", default="")),
            "timeline_name": norm_text(safe_call(timeline, "GetName", default="")),
            "v3_track": v3_track,
            "v3_track_name": track_name(timeline, "video", v3_track),
            "v3_candidate_count": len(items),
            "plan_item_count": len(plan_items),
            "profile_calibration": plan.get("profile_calibration") or {},
            "visual_review_samples": plan.get("visual_review_samples") or [],
            "core_tracks_before": before_tracks,
        })

        preflight = {"ok": True, "missing_plan_items": [], "missing_textplus": [], "font_mismatches": [], "baseline_conflicts": [], "size_keyframes": []}
        item_contexts = []
        tolerance = float(config.get("size_tolerance") or 1e-7)
        baseline_tolerance = float(config.get("baseline_tolerance") or 1e-6)

        if len(items) != expected:
            failures.append("v3_candidate_count_mismatch")
        if len(plan_items) != expected:
            failures.append("plan_item_count_mismatch")

        for item in items:
            name = timeline_item_name(item)
            plan_item = plan_by_name.get(name)
            if plan_item is None:
                preflight["missing_plan_items"].append(name)
                continue
            tool, diagnostics = find_textplus_tool(item)
            if tool is None:
                preflight["missing_textplus"].append({"name": name, "diagnostics": diagnostics})
                continue
            actual_family = norm_text(get_input_value(tool, "Font"))
            actual_face = norm_text(get_input_value(tool, "Style") or "Regular")
            expected_family = norm_text(plan_item.get("expected_family"))
            expected_face = norm_text(plan_item.get("expected_face") or "Regular")
            if norm_token(actual_family) != norm_token(expected_family) or norm_token(actual_face) != norm_token(expected_face):
                preflight["font_mismatches"].append({"name": name, "expected": [expected_family, expected_face], "actual": [actual_family, actual_face]})
            current_size = finite(get_input_value(tool, "Size"))
            baseline_size = finite(plan_item.get("baseline_size"))
            target_size = finite(plan_item.get("target_size"))
            size_kf = input_keyframes(tool, "Size")
            if not keyframes_empty(size_kf):
                preflight["size_keyframes"].append({"name": name, "keyframes": size_kf})
            if current_size is None or baseline_size is None or target_size is None:
                preflight["baseline_conflicts"].append({"name": name, "reason": "missing_numeric_size", "current": current_size, "baseline": baseline_size, "target": target_size})
            elif not floats_equal(current_size, baseline_size, baseline_tolerance) and not floats_equal(current_size, target_size, tolerance):
                preflight["baseline_conflicts"].append({"name": name, "reason": "live_size_matches_neither_baseline_nor_target", "current": current_size, "baseline": baseline_size, "target": target_size})
            item_contexts.append((item, tool, plan_item, diagnostics))

        if preflight["missing_plan_items"]:
            failures.append("missing_plan_items")
        if preflight["missing_textplus"]:
            failures.append("missing_textplus")
        if preflight["font_mismatches"]:
            failures.append("step_3B_1_font_mapping_not_intact")
        if preflight["baseline_conflicts"]:
            failures.append("stale_or_conflicting_size_baseline")
        if preflight["size_keyframes"] and bool(config.get("reject_size_keyframes", True)):
            failures.append("size_keyframes_present_blocked_for_safety")
        preflight["ok"] = not failures and len(item_contexts) == expected
        report["preflight"] = preflight

        if not preflight["ok"]:
            report.update({"status": "blocked_before_writes", "failures": failures, "warnings": warnings, "items": [], "runtime_seconds": round(time.time() - started, 3)})
            write_json(report_path, report)
            raise RuntimeError("Step 3B.2 preflight blocked all writes: " + ", ".join(failures))

        modified = 0
        already = 0
        readback_success = 0
        failed = 0
        preserved_failures = 0
        font_integrity_failures = 0
        stale_baseline_count = 0
        output_items = []
        dry_run = bool(config.get("dry_run", False))
        delay = float(config.get("readback_delay_sec") or 0.0)

        for item, tool, plan_item, diagnostics in item_contexts:
            name = timeline_item_name(item)
            target = float(plan_item["target_size"])
            baseline = float(plan_item["baseline_size"])
            before = snapshot_inputs(tool, ["StyledText", "Font", "Style", "Center", "Size"])
            current = finite(before["Size"]["value"])
            status = "pending"
            write_info = None
            rollback = None
            item_failures: List[str] = []

            if current is None:
                status = "failed"
                item_failures.append("live_size_not_numeric")
            elif floats_equal(current, target, tolerance):
                status = "already_correct"
                already += 1
            elif not floats_equal(current, baseline, baseline_tolerance):
                status = "failed"
                stale_baseline_count += 1
                item_failures.append("stale_baseline")
            elif dry_run:
                status = "dry_run_would_modify"
                modified += 1
            else:
                write_info = set_input_static(tool, "Size", target)
                if delay > 0:
                    time.sleep(delay)
                after_size = finite(get_input_value(tool, "Size"))
                if write_info.get("ok") and floats_equal(after_size, target, tolerance):
                    status = "modified"
                    modified += 1
                else:
                    status = "failed"
                    item_failures.append("size_write_or_readback_failed")
                    if bool(config.get("rollback_on_item_failure", True)):
                        rollback = set_input_static(tool, "Size", baseline)

            after = snapshot_inputs(tool, ["StyledText", "Font", "Style", "Center", "Size"])
            preserved_before = {k: v for k, v in before.items() if k != "Size"}
            preserved_after = {k: v for k, v in after.items() if k != "Size"}
            preserved_ok = values_equal(preserved_before, preserved_after)
            if not preserved_ok:
                preserved_failures += 1
                item_failures.append("non_size_inputs_changed")
            font_ok = norm_token(after["Font"]["value"]) == norm_token(plan_item.get("expected_family")) and norm_token(after["Style"]["value"] or "Regular") == norm_token(plan_item.get("expected_face") or "Regular")
            if not font_ok:
                font_integrity_failures += 1
                item_failures.append("font_mapping_changed")
            size_kf_ok = values_equal(before["Size"]["keyframes"], after["Size"]["keyframes"])
            if not size_kf_ok:
                item_failures.append("size_keyframes_changed")
            final_size = finite(after["Size"]["value"])
            readback_ok = status in {"modified", "already_correct", "dry_run_would_modify"} and (dry_run or floats_equal(final_size, target, tolerance))
            if readback_ok:
                readback_success += 1
            if item_failures:
                failed += 1

            output_items.append({
                "name": name,
                "cue_id": plan_item.get("cue_id"),
                "cue_index": plan_item.get("cue_index"),
                "start": timeline_item_start(item),
                "end": timeline_item_end(item),
                "rendered_text": plan_item.get("rendered_text"),
                "style_profile_id": plan_item.get("style_profile_id"),
                "family": plan_item.get("expected_family"),
                "face": plan_item.get("expected_face"),
                "profile_multiplier": plan_item.get("profile_multiplier"),
                "baseline_size": baseline,
                "target_size": target,
                "size_before": current,
                "size_after": final_size,
                "status": status,
                "write": write_info,
                "rollback": rollback,
                "preserved_inputs_ok": preserved_ok,
                "font_integrity_ok": font_ok,
                "size_keyframes_unchanged": size_kf_ok,
                "readback_ok": readback_ok,
                "failures": item_failures,
                "diagnostics": diagnostics,
            })

        after_tracks = core_track_snapshot(timeline, v3_track)
        core_ok = values_equal(before_tracks, after_tracks)
        if not core_ok:
            failures.append("core_track_integrity_false")
        if failed:
            failures.append("one_or_more_items_failed")
        if preserved_failures:
            failures.append("preserved_input_failure_count_nonzero")
        if font_integrity_failures:
            failures.append("font_integrity_failure_count_nonzero")
        if readback_success != expected:
            failures.append("readback_success_count_mismatch")

        report.update({
            "ok": not failures,
            "status": "applied_and_verified" if not failures else "completed_with_failures",
            "modified_count": modified,
            "already_correct_count": already,
            "mapped_count": len(item_contexts),
            "readback_success_count": readback_success,
            "failed_count": failed,
            "preserved_input_failure_count": preserved_failures,
            "font_integrity_failure_count": font_integrity_failures,
            "stale_baseline_count": stale_baseline_count,
            "size_keyframe_input_count": len(preflight["size_keyframes"]),
            "items": output_items,
            "core_tracks_after": after_tracks,
            "core_track_integrity": {"ok": core_ok},
            "warnings": warnings,
            "failures": failures,
            "runtime_seconds": round(time.time() - started, 3),
        })
        write_json(report_path, report)
        return_code = 0 if report["ok"] else 1
        status_payload = {
            "ok": report["ok"], "running": False, "step": "Major Step 3B.2", "version": VERSION,
            "launch_id": launch_id, "finished_at_unix": now_unix(), "return_code": return_code,
            "report_path": str(report_path), "report_exists": report_path.is_file(), "report_status": report.get("status"),
            "v3_candidate_count": report.get("v3_candidate_count"), "mapped_count": report.get("mapped_count"),
            "modified_count": modified, "already_correct_count": already, "readback_success_count": readback_success,
            "failed_count": failed, "failures": failures,
        }
        write_json(status_path, status_payload)
        append_log(log_path, "workspace_script_finished", status_payload)
        if bool(config.get("show_completion_message", True)):
            show_message(
                "Video Cloner — Step 3B.2 complete" if report["ok"] else "Video Cloner — Step 3B.2 failed",
                "Font-size calibration finished.\n\n"
                f"V3 clips: {len(items)}\nMapped: {len(item_contexts)}\nModified: {modified}\n"
                f"Already correct: {already}\nFailures: {failed}\n\nReport:\n{report_path}",
                is_error=not report["ok"],
            )
        return return_code
    except Exception as exc:
        if not report_path.is_file():
            report.update({"ok": False, "status": "exception", "exception": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(), "failures": failures or ["workspace_exception"], "runtime_seconds": round(time.time() - started, 3)})
            write_json(report_path, report)
        status_payload = {"ok": False, "running": False, "step": "Major Step 3B.2", "version": VERSION, "launch_id": launch_id, "finished_at_unix": now_unix(), "return_code": 1, "report_path": str(report_path), "report_exists": report_path.is_file(), "exception": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
        write_json(status_path, status_payload)
        append_log(log_path, "workspace_script_failed", status_payload)
        if bool(config.get("show_completion_message", True)):
            show_message("Video Cloner — Step 3B.2 failed", f"{type(exc).__name__}: {exc}\n\nReport:\n{report_path}\n\nStatus:\n{status_path}", is_error=True)
        return 1


_AUTORUN_DONE = False

def _workspace_autorun() -> None:
    global _AUTORUN_DONE
    if _AUTORUN_DONE:
        return
    _AUTORUN_DONE = True
    run()


_workspace_autorun()
