"""Render exact Text+ on/off image sequences for glyph-mask extraction.

This probe does not remove captions and does not modify the accepted V5
caption timeline. It renders frames 420-462 twice from the retained V5
timeline: once unchanged, then once from a disposable duplicate where only
the 115 generated Text+ timeline items are disabled. The duplicate, render
jobs, current page, current timeline, render format/codec, and render mode are
restored or removed before the run finishes.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

V5_MODULE_PATH = Path(__file__).with_name("step_3D_full_lifecycle_textplus_rollout.py")
_spec = importlib.util.spec_from_file_location("vc_step3d_rollout_v5_for_glyph_probe", V5_MODULE_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot_load:{V5_MODULE_PATH}")
v5 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = v5
_spec.loader.exec_module(v5)
base = v5.base

TASK_ID = "DZSQH7AUHJT_STEP_3D_GLYPH_MASK_RENDER_PROBE_V1"
MODE = "STEP_3D_GLYPH_MASK_RENDER_PROBE"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3D_glyph_mask_render_probe.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_full_step_3D_complete"
V5_TASK_ID = "DZSQH7AUHJT_STEP_3D_FULL_LIFECYCLE_TEXTPLUS_ROLLOUT_V5"
V5_RUN_ID = "20260805T202712503703Z_e039870f2fb44156a6c662d1df9c2a77"
V5_REPORT_RELATIVE_PATH = (
    f".agent/reports/{V5_TASK_ID}/{V5_RUN_ID}/report.json"
)
V5_PLAN_RELATIVE_PATH = (
    f".agent/reports/{V5_TASK_ID}/{V5_RUN_ID}/rollout_plan.json"
)
ACCEPTED_STATE_RELATIVE_PATH = ".agent/state/latest_accepted.json"
FRAME_IN = 420
FRAME_OUT = 462
EXPECTED_FRAME_COUNT = FRAME_OUT - FRAME_IN + 1
EXPECTED_TEXTPLUS_COUNT = 115
TEMP_TIMELINE_PREFIX = "VC_STEP3D_GLYPH_MASK_PROBE_"
RENDER_TIMEOUT_SECONDS = 900.0
POLL_SECONDS = 0.25
LOSSLESS_EXTENSIONS = ("png", "tif", "tiff", "exr", "dpx")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    base.write_json(path, payload)


def normalize_extension(value: Any) -> str:
    return str(value or "").strip().lower().lstrip(".")


def codec_score(extension: str, description: str, value: str) -> Tuple[int, str, str]:
    text = f"{description} {value}".lower()
    score = 0
    if extension == "png":
        score += 500
    elif extension in {"tif", "tiff"}:
        score += 400
    elif extension == "exr":
        score += 300
    elif extension == "dpx":
        score += 200
    for needle, points in (
        ("16-bit", 80),
        ("16 bit", 80),
        ("rgb", 60),
        ("rgba", 55),
        ("lossless", 50),
        ("float", 40),
        ("half", 35),
        ("10-bit", 25),
        ("10 bit", 25),
        ("8-bit", 10),
        ("8 bit", 10),
    ):
        if needle in text:
            score += points
    return score, str(description), str(value)


def select_lossless_render_format(formats: Mapping[str, Any], codecs_by_format: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    for render_format, raw_extension in formats.items():
        extension = normalize_extension(raw_extension)
        if extension not in LOSSLESS_EXTENSIONS:
            continue
        codecs = codecs_by_format.get(str(render_format)) or {}
        if not isinstance(codecs, Mapping) or not codecs:
            continue
        for description, codec_value in codecs.items():
            score, _, _ = codec_score(extension, str(description), str(codec_value))
            candidates.append(
                {
                    "format": str(render_format),
                    "extension": extension,
                    "codec_description": str(description),
                    "codec": str(codec_value),
                    "score": score,
                }
            )
    candidates.sort(
        key=lambda row: (
            -int(row["score"]),
            str(row["format"]).lower(),
            str(row["codec_description"]).lower(),
        )
    )
    if not candidates:
        return {"ok": False, "candidates": [], "error": "lossless_image_sequence_unavailable"}
    return {"ok": True, "selected": candidates[0], "candidates": candidates}


def timeline_dimensions(timeline: Any, project: Any) -> Dict[str, Any]:
    def value(name: str, default: Any = None) -> Any:
        result = base.safe_value(timeline, "GetSetting", name, default=None)
        if result in (None, ""):
            result = base.safe_value(project, "GetSetting", name, default=default)
        return result

    width = base.as_int(value("timelineResolutionWidth", 1080), 1080)
    height = base.as_int(value("timelineResolutionHeight", 1920), 1920)
    raw_rate = value("timelineFrameRate", 25)
    try:
        frame_rate = float(str(raw_rate).split()[0])
    except (TypeError, ValueError):
        frame_rate = 25.0
    return {"width": width, "height": height, "frame_rate": frame_rate}


def build_render_settings(target_dir: Path, custom_name: str, dimensions: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "SelectAllFrames": False,
        "MarkIn": FRAME_IN,
        "MarkOut": FRAME_OUT,
        "TargetDir": str(target_dir),
        "CustomName": custom_name,
        "UniqueFilenameStyle": 1,
        "ExportVideo": True,
        "ExportAudio": False,
        "FormatWidth": int(dimensions["width"]),
        "FormatHeight": int(dimensions["height"]),
        "FrameRate": float(dimensions["frame_rate"]),
        "PixelAspectRatio": "square",
        "ReplaceExistingFilesInPlace": True,
    }


def status_text(status: Any) -> str:
    if not isinstance(status, Mapping):
        return ""
    for key in ("JobStatus", "jobStatus", "Status", "status"):
        value = status.get(key)
        if value is not None:
            return str(value).strip().lower()
    return ""


def status_is_success(status: Any) -> bool:
    text = status_text(status)
    return text in {"complete", "completed", "success", "succeeded"}


def status_is_failure(status: Any) -> bool:
    text = status_text(status)
    return any(token in text for token in ("fail", "cancel", "error"))


def list_render_files(directory: Path, extension: str) -> List[Path]:
    return sorted(
        [path for path in directory.rglob(f"*.{extension}") if path.is_file()],
        key=lambda path: path.name.lower(),
    )


def render_sequence(
    project: Any,
    timeline: Any,
    output_dir: Path,
    custom_name: str,
    selection: Mapping[str, Any],
    dimensions: Mapping[str, Any],
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=False)
    calls: List[Dict[str, Any]] = []
    job_id: Optional[str] = None
    started_at = base.utc_now()
    try:
        selected_timeline, call = base.direct_call(project, "SetCurrentTimeline", timeline)
        calls.append(call)
        if not selected_timeline:
            raise RuntimeError("set_current_timeline")

        set_format, call = base.direct_call(
            project,
            "SetCurrentRenderFormatAndCodec",
            str(selection["format"]),
            str(selection["codec"]),
        )
        calls.append(call)
        if not set_format:
            raise RuntimeError("set_render_format_codec")

        set_mode, call = base.direct_call(project, "SetCurrentRenderMode", 1)
        calls.append(call)
        if not set_mode:
            raise RuntimeError("set_render_mode")

        settings = build_render_settings(output_dir, custom_name, dimensions)
        settings_ok, call = base.direct_call(project, "SetRenderSettings", settings)
        calls.append(call)
        if not settings_ok:
            raise RuntimeError("set_render_settings")

        raw_job_id, call = base.direct_call(project, "AddRenderJob")
        calls.append(call)
        job_id = str(raw_job_id or "")
        if not job_id:
            raise RuntimeError("add_render_job")

        started, call = base.direct_call(project, "StartRendering", job_id)
        calls.append(call)
        if not started:
            raise RuntimeError("start_rendering")

        deadline = time.monotonic() + RENDER_TIMEOUT_SECONDS
        status_rows: List[Dict[str, Any]] = []
        terminal_status: Any = None
        while time.monotonic() < deadline:
            raw_status = base.safe_value(project, "GetRenderJobStatus", job_id, default={})
            rendering = bool(base.safe_value(project, "IsRenderingInProgress", default=False))
            row = {
                "status": base.json_safe(raw_status),
                "status_text": status_text(raw_status),
                "rendering": rendering,
                "observed_at": base.utc_now(),
            }
            if not status_rows or row["status_text"] != status_rows[-1].get("status_text") or rendering != status_rows[-1].get("rendering"):
                status_rows.append(row)
            if status_is_failure(raw_status):
                terminal_status = raw_status
                raise RuntimeError(f"render_failed:{status_text(raw_status)}")
            if status_is_success(raw_status) and not rendering:
                terminal_status = raw_status
                break
            time.sleep(POLL_SECONDS)
        else:
            raise RuntimeError("render_timeout")

        files = list_render_files(output_dir, str(selection["extension"]))
        return {
            "ok": len(files) == EXPECTED_FRAME_COUNT,
            "started_at": started_at,
            "finished_at": base.utc_now(),
            "timeline_name": base.timeline_name(timeline),
            "timeline_unique_id": base.timeline_unique_id(timeline),
            "output_dir": str(output_dir),
            "custom_name": custom_name,
            "selection": dict(selection),
            "dimensions": dict(dimensions),
            "render_settings": settings,
            "job_id": job_id,
            "terminal_status": base.json_safe(terminal_status),
            "status_rows": status_rows,
            "file_count": len(files),
            "files": [str(path) for path in files],
            "calls": calls,
            "error": None if len(files) == EXPECTED_FRAME_COUNT else f"render_file_count:{len(files)}",
        }
    except BaseException as exc:
        return {
            "ok": False,
            "started_at": started_at,
            "finished_at": base.utc_now(),
            "timeline_name": base.timeline_name(timeline),
            "output_dir": str(output_dir),
            "custom_name": custom_name,
            "selection": dict(selection),
            "dimensions": dict(dimensions),
            "job_id": job_id,
            "calls": calls,
            "error": base.compact_exception(exc),
            "traceback": traceback.format_exc(),
            "file_count": len(list_render_files(output_dir, str(selection["extension"]))) if output_dir.exists() else 0,
        }
    finally:
        if job_id:
            base.direct_call(project, "DeleteRenderJob", job_id)


def expected_target_names(plan: Mapping[str, Any]) -> List[str]:
    instances = plan.get("instances") if isinstance(plan.get("instances"), list) else []
    names = [str(row.get("target_name") or "") for row in instances if isinstance(row, Mapping)]
    if len(names) != EXPECTED_TEXTPLUS_COUNT or any(not name for name in names) or len(set(names)) != len(names):
        raise ValueError("v5_target_names")
    return names


def find_items_by_name(timeline: Any, names: Iterable[str]) -> Dict[str, Tuple[int, Any]]:
    wanted = set(names)
    found: Dict[str, Tuple[int, Any]] = {}
    for track in range(1, base.track_count(timeline, "video") + 1):
        for item in base.track_items(timeline, "video", track):
            name = base.item_name(item)
            if name in wanted:
                if name in found:
                    raise RuntimeError(f"duplicate_target_item:{name}")
                found[name] = (track, item)
    return found


def disable_generated_items(timeline: Any, names: Sequence[str]) -> Dict[str, Any]:
    found = find_items_by_name(timeline, names)
    rows: List[Dict[str, Any]] = []
    for name in names:
        track, item = found.get(name, (0, None))
        before = base.safe_value(item, "GetClipEnabled", default=None) if item is not None else None
        value, call = base.direct_call(item, "SetClipEnabled", False) if item is not None else (None, {"error": "item_missing"})
        after = base.safe_value(item, "GetClipEnabled", default=None) if item is not None else None
        ok = bool(item is not None and value is not False and after is False)
        rows.append(
            {
                "name": name,
                "track": track,
                "before": base.json_safe(before),
                "after": base.json_safe(after),
                "call": call,
                "ok": ok,
            }
        )
    return {
        "expected_count": len(names),
        "found_count": len(found),
        "disabled_count": sum(1 for row in rows if row["ok"]),
        "rows": rows,
        "ok": len(found) == len(names) and all(row["ok"] for row in rows),
    }


def timeline_inventory(timeline: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for track in range(1, base.track_count(timeline, "video") + 1):
        for item in base.track_items(timeline, "video", track):
            row = base.item_summary(track, item)
            row["clip_enabled"] = base.json_safe(base.safe_value(item, "GetClipEnabled", default=None))
            rows.append(row)
    return sorted(rows, key=lambda row: (int(row["track_index"]), int(row["start"]), str(row["name"])))


def compare_stable_inventory(left: Sequence[Mapping[str, Any]], right: Sequence[Mapping[str, Any]], ignored_names: Iterable[str] = ()) -> Dict[str, Any]:
    ignored = set(ignored_names)
    fields = ("name", "track_index", "start", "end", "duration", "media_pool_item_name", "fusion_comp_count")

    def project(rows: Sequence[Mapping[str, Any]]) -> List[Tuple[Any, ...]]:
        return sorted(tuple(row.get(field) for field in fields) for row in rows if str(row.get("name") or "") not in ignored)

    left_rows = project(left)
    right_rows = project(right)
    return {"fields": list(fields), "left_count": len(left_rows), "right_count": len(right_rows), "matched": left_rows == right_rows, "ok": left_rows == right_rows}


def cleanup(
    resolve: Any,
    project_manager: Any,
    project: Any,
    media_pool: Any,
    temporary_name: str,
    original_timeline: Any,
    original_page: str,
    original_render: Mapping[str, Any],
    accepted_path: Path,
    accepted_hash: str,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"errors": [], "calls": [], "save_call_count": 0}
    try:
        temporary = base.find_timeline(project, temporary_name)
        if temporary is not None:
            value, call = base.direct_call(media_pool, "DeleteTimelines", [temporary])
            result["calls"].append(call)
            if not value:
                result["errors"].append("delete_temporary")
        result["temporary_deleted"] = base.find_timeline(project, temporary_name) is None

        if original_timeline is not None:
            value, call = base.direct_call(project, "SetCurrentTimeline", original_timeline)
            result["calls"].append(call)
            if not value:
                result["errors"].append("restore_timeline")

        original_format = str(original_render.get("format") or "")
        original_codec = str(original_render.get("codec") or "")
        if original_format and original_codec:
            value, call = base.direct_call(project, "SetCurrentRenderFormatAndCodec", original_format, original_codec)
            result["calls"].append(call)
            if not value:
                result["errors"].append("restore_render_format")
        original_mode = original_render.get("mode")
        if isinstance(original_mode, int):
            value, call = base.direct_call(project, "SetCurrentRenderMode", original_mode)
            result["calls"].append(call)
            if not value:
                result["errors"].append("restore_render_mode")
        base.direct_call(project, "SetRenderSettings", {"SelectAllFrames": True})

        if original_page:
            value, call = base.direct_call(resolve, "OpenPage", original_page)
            result["calls"].append(call)
            if not value:
                result["errors"].append("restore_page")

        save = v5.base.save_project(project_manager)
        result["save"] = save
        result["save_call_count"] = 1
        if not save.get("success"):
            result["errors"].append("save_cleanup")
    except BaseException as exc:
        result["errors"].append(base.compact_exception(exc))
        result["traceback"] = traceback.format_exc()
    result["accepted_state_unchanged"] = accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash
    result["ok"] = bool(not result["errors"] and result.get("temporary_deleted") and result["accepted_state_unchanged"])
    return result


def run(resolve: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    root = base.repository_root()
    command = context.get("command") if isinstance(context, dict) else None
    if not isinstance(command, dict):
        raise ValueError("command")
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    if not run_id:
        raise ValueError("run_id")
    if command.get("task_id") != TASK_ID or command.get("mode") != MODE:
        raise ValueError("command_identity")

    report_dir = base.relative_path(root, command.get("artifacts_dir"))
    report_dir.mkdir(parents=True, exist_ok=True)
    accepted_path = root / ACCEPTED_STATE_RELATIVE_PATH
    accepted_hash = str(command.get("accepted_state_sha256") or "")
    temporary_name = f"{TEMP_TIMELINE_PREFIX}{run_id[-12:]}"

    report: Dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "backend": "resolve_lossless_dual_render_plus_textplus_disable",
        "ok": False,
        "started_at": base.utc_now(),
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "temporary_timeline_name": temporary_name,
        "frame_in": FRAME_IN,
        "frame_out": FRAME_OUT,
        "expected_frame_count": EXPECTED_FRAME_COUNT,
        "failures": [],
        "save_call_count": 0,
    }

    original_timeline = None
    original_page = str(base.safe_value(resolve, "GetCurrentPage", default="") or "")
    project_manager = project = media_pool = None
    original_render: Dict[str, Any] = {}
    source_before: List[Dict[str, Any]] = []
    source_unique_id = ""

    try:
        source_contract = base.verify_source_contract(root, command)
        report["source_contract_verified_count"] = source_contract["verified_count"]
        write_json(report_dir / "source_contract_verification.json", source_contract)

        if not accepted_path.is_file() or base.raw_sha256(accepted_path) != accepted_hash:
            raise RuntimeError("accepted_state")

        v5_report = load_json(root / V5_REPORT_RELATIVE_PATH)
        v5_plan = load_json(root / V5_PLAN_RELATIVE_PATH)
        if not (
            v5_report.get("ok") is True
            and v5_report.get("task_id") == V5_TASK_ID
            and v5_report.get("run_id") == V5_RUN_ID
            and v5_report.get("final_timeline_name") == SOURCE_TIMELINE_NAME
            and v5_report.get("persistent_instance_count") == EXPECTED_TEXTPLUS_COUNT
            and v5_report.get("final_timeline_kept") is True
        ):
            raise RuntimeError("v5_report_contract")
        target_names = expected_target_names(v5_plan)

        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        original_timeline = base.safe_value(project, "GetCurrentTimeline", default=None)
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        if base.find_timeline(project, temporary_name) is not None:
            raise RuntimeError("temporary_timeline_exists")
        source_unique_id = base.timeline_unique_id(source)
        source_before = timeline_inventory(source)
        source_targets = find_items_by_name(source, target_names)
        if len(source_targets) != EXPECTED_TEXTPLUS_COUNT:
            raise RuntimeError(f"source_target_count:{len(source_targets)}")

        raw_formats = base.safe_value(project, "GetRenderFormats", default={})
        if not isinstance(raw_formats, Mapping) or not raw_formats:
            raise RuntimeError("render_formats")
        codecs_by_format: Dict[str, Mapping[str, Any]] = {}
        for render_format in raw_formats:
            codecs = base.safe_value(project, "GetRenderCodecs", str(render_format), default={})
            codecs_by_format[str(render_format)] = codecs if isinstance(codecs, Mapping) else {}
        render_selection = select_lossless_render_format(raw_formats, codecs_by_format)
        write_json(
            report_dir / "render_capability.json",
            {
                "formats": base.json_safe(raw_formats),
                "codecs_by_format": base.json_safe(codecs_by_format),
                "selection": render_selection,
            },
        )
        if not render_selection.get("ok"):
            raise RuntimeError("lossless_render_format")
        selected = render_selection["selected"]

        current_render = base.safe_value(project, "GetCurrentRenderFormatAndCodec", default={})
        if isinstance(current_render, Mapping):
            original_render.update({"format": current_render.get("format"), "codec": current_render.get("codec")})
        original_render["mode"] = base.as_int(base.safe_value(project, "GetCurrentRenderMode", default=1), 1)
        dimensions = timeline_dimensions(source, project)
        timeline_start = base.as_int(base.safe_value(source, "GetStartFrame", default=0), 0)
        timeline_end = base.as_int(base.safe_value(source, "GetEndFrame", default=0), 0)
        if not (timeline_start <= FRAME_IN <= FRAME_OUT <= timeline_end):
            raise RuntimeError(f"render_range:{timeline_start}:{timeline_end}")

        opened, open_call = base.direct_call(resolve, "OpenPage", "deliver")
        if not opened:
            raise RuntimeError("open_deliver")

        preflight = {
            "resolve_calls": resolve_calls,
            "open_deliver_call": open_call,
            "original_page": original_page,
            "original_timeline_name": base.timeline_name(original_timeline) if original_timeline is not None else None,
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "source_timeline_unique_id": source_unique_id,
            "source_item_count": len(source_before),
            "target_name_count": len(target_names),
            "render_selection": selected,
            "dimensions": dimensions,
            "timeline_start": timeline_start,
            "timeline_end": timeline_end,
            "frame_in": FRAME_IN,
            "frame_out": FRAME_OUT,
        }
        write_json(report_dir / "glyph_render_preflight.json", preflight)

        with_dir = report_dir / "render_with_textplus"
        with_result = render_sequence(project, source, with_dir, "with_textplus", selected, dimensions)
        write_json(report_dir / "render_with_textplus.json", with_result)
        if not with_result.get("ok"):
            raise RuntimeError(f"render_with_textplus:{with_result.get('error')}")

        duplicate_value, duplicate_call = base.direct_call(source, "DuplicateTimeline", temporary_name)
        temporary = duplicate_value if duplicate_value is not None else base.find_timeline(project, temporary_name)
        if temporary is None:
            raise RuntimeError("duplicate_timeline")
        selected_temp, select_temp_call = base.direct_call(project, "SetCurrentTimeline", temporary)
        if not selected_temp:
            raise RuntimeError("select_temporary")

        temp_before = timeline_inventory(temporary)
        inventory_comparison = compare_stable_inventory(source_before, temp_before)
        disabled = disable_generated_items(temporary, target_names)
        temp_after = timeline_inventory(temporary)
        setup = {
            "duplicate_call": duplicate_call,
            "select_call": select_temp_call,
            "inventory_comparison": inventory_comparison,
            "disabled": disabled,
            "temporary_inventory_before": temp_before,
            "temporary_inventory_after": temp_after,
            "ok": bool(inventory_comparison.get("ok") and disabled.get("ok")),
        }
        write_json(report_dir / "temporary_timeline_setup.json", setup)
        if not setup["ok"]:
            raise RuntimeError("temporary_timeline_setup")

        without_dir = report_dir / "render_without_textplus"
        without_result = render_sequence(project, temporary, without_dir, "without_textplus", selected, dimensions)
        write_json(report_dir / "render_without_textplus.json", without_result)
        if not without_result.get("ok"):
            raise RuntimeError(f"render_without_textplus:{without_result.get('error')}")

        render_result = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "frame_in": FRAME_IN,
            "frame_out": FRAME_OUT,
            "expected_frame_count": EXPECTED_FRAME_COUNT,
            "extension": selected["extension"],
            "render_selection": selected,
            "dimensions": dimensions,
            "with_textplus_files": with_result["files"],
            "without_textplus_files": without_result["files"],
            "target_names": target_names,
            "target_count": len(target_names),
            "ok": True,
        }
        write_json(report_dir / "glyph_render_result.json", render_result)

        source_after = timeline_inventory(source)
        source_comparison = compare_stable_inventory(source_before, source_after)
        report.update(
            {
                "render_format": selected["format"],
                "render_codec": selected["codec"],
                "render_extension": selected["extension"],
                "with_textplus_frame_count": with_result["file_count"],
                "without_textplus_frame_count": without_result["file_count"],
                "disabled_textplus_count": disabled["disabled_count"],
                "source_timeline_unchanged": source_comparison["ok"] and base.timeline_unique_id(source) == source_unique_id,
                "render_sequences_complete": True,
            }
        )
        if not report["source_timeline_unchanged"]:
            raise RuntimeError("source_timeline_changed")
    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc))
        report["error"] = base.compact_exception(exc)
        report["traceback"] = traceback.format_exc()
    finally:
        if project_manager is not None and project is not None and media_pool is not None:
            cleanup_result = cleanup(
                resolve,
                project_manager,
                project,
                media_pool,
                temporary_name,
                original_timeline,
                original_page,
                original_render,
                accepted_path,
                accepted_hash,
            )
        else:
            cleanup_result = {
                "ok": accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash,
                "temporary_deleted": True,
                "accepted_state_unchanged": accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash,
                "save_call_count": 0,
                "errors": [],
            }
        write_json(report_dir / "cleanup.json", cleanup_result)
        report["temporary_timeline_deleted"] = cleanup_result.get("temporary_deleted") is True
        report["accepted_state_unchanged"] = cleanup_result.get("accepted_state_unchanged") is True
        report["save_call_count"] = cleanup_result.get("save_call_count", 0)
        if not cleanup_result.get("ok"):
            report["failures"].append("cleanup")

    report["finished_at"] = base.utc_now()
    report["visual_review_required"] = True
    report["ok"] = bool(
        not report["failures"]
        and report.get("render_sequences_complete") is True
        and report.get("with_textplus_frame_count") == EXPECTED_FRAME_COUNT
        and report.get("without_textplus_frame_count") == EXPECTED_FRAME_COUNT
        and report.get("disabled_textplus_count") == EXPECTED_TEXTPLUS_COUNT
        and report.get("source_timeline_unchanged") is True
        and report.get("temporary_timeline_deleted") is True
        and report.get("accepted_state_unchanged") is True
        and report.get("save_call_count") == 1
    )
    return report
