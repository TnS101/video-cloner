"""One-item live proof of the production Fusion Composition + TextPlus backend.

This V2 probe corrects the V1 test context. It duplicates the trusted populated
source timeline, opens the Edit page, creates and isolates one empty video track,
calls the exact production provisioning helper once, verifies two persistent
Center keyframes, then deletes the disposable duplicate.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

TASK_ID = "DZSQH7AUHJT_STEP_3D_TEXTPLUS_CARRIER_PROBE_V2"
MODE = "STEP_3D_TEXTPLUS_CARRIER_PROBE_V2"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3D_textplus_carrier_probe_v2.py"
BASE_MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3D_textplus_carrier_probe.py"
CONTROLLER_RELATIVE_PATH = "resolve_workspace/resolve_apply_video_cloner_metadata.py"
ANIMATION_RELATIVE_PATH = "resolve_workspace/resolve_apply_caption_animation_step_3C.py"
BRIDGE_RELATIVE_PATH = "resolve_workspace/VC_Agent_Bridge.py"
SOURCE_PATHS = (
    MODULE_RELATIVE_PATH,
    BASE_MODULE_RELATIVE_PATH,
    CONTROLLER_RELATIVE_PATH,
    ANIMATION_RELATIVE_PATH,
    BRIDGE_RELATIVE_PATH,
)
ACCEPTED_STATE_RELATIVE_PATH = ".agent/state/latest_accepted.json"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"

PROTECTED_SOURCE_TIMELINE = "DZsqH7auhjt_textplus_full"
PROTECTED_CAPTION_PREFIX = "VC_TEXTPLUS_"
PROTECTED_CAPTION_COUNT = 116
PROBE_TEXT = "VC_TEXTPLUS_CARRIER_PROBE_V2"
TARGET_TRACK = 5
TARGET_START_FRAME = 430
PROBE_DURATION_FRAMES = 48
CENTER_FRAME_0 = [0.50, 0.50]
CENTER_FRAME_3 = [0.42, 0.58]


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def normalized_sha256(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def compact_exception(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return repr(value)


def load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"module_spec:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_inside_root(root: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"command_{field}")
    candidate = Path(value)
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"command_{field}_outside_repository") from exc
    return path


def verify_source_contract(root: Path, command: Dict[str, Any]) -> Dict[str, Any]:
    contract = command.get("source_contract")
    if not isinstance(contract, dict):
        raise ValueError("source_contract")
    if contract.get("version") != 1:
        raise ValueError("source_contract_version")
    if contract.get("algorithm") != SOURCE_HASH_ALGORITHM:
        raise ValueError("source_contract_algorithm")
    hashes = contract.get("hashes")
    expected = set(SOURCE_PATHS)
    if not isinstance(hashes, dict) or set(hashes) != expected:
        raise ValueError("source_contract_paths")
    rows = []
    for relative in sorted(expected):
        path = root / relative
        if not path.is_file():
            raise ValueError(f"source_contract_missing:{relative}")
        actual = normalized_sha256(path)
        wanted = hashes.get(relative)
        matched = actual == wanted
        rows.append(
            {
                "path": relative,
                "expected": wanted,
                "actual": actual,
                "matched": matched,
            }
        )
        if not matched:
            raise ValueError(f"source_contract_hash:{relative}")
    return {
        "version": 1,
        "algorithm": SOURCE_HASH_ALGORITHM,
        "verified_count": len(rows),
        "rows": rows,
    }


def load_runtime(root: Path) -> Tuple[Any, Any, Any]:
    base = load_module(root / BASE_MODULE_RELATIVE_PATH, "vc_textplus_probe_v1_helpers")
    controller = load_module(root / CONTROLLER_RELATIVE_PATH, "vc_textplus_controller_v2")
    animation = load_module(root / ANIMATION_RELATIVE_PATH, "vc_textplus_animation_v2")
    required_controller = (
        "provision_textplus_fusion_composition",
        "get_or_create_existing_title_text_tool",
        "set_fusion_input_best_effort",
        "try_read_fusion_input",
        "fusion_input_values_equivalent",
        "timeline_item_name",
        "timeline_item_start",
        "timeline_item_end",
        "timeline_item_track_info",
        "timeline_item_unique_id",
        "get_track_count",
        "get_track_items",
        "ensure_video_track",
        "set_track_name_best_effort",
        "apply_subtitle_track_guard",
        "restore_track_locks",
    )
    required_animation = (
        "ensure_modifier",
        "write_key",
        "read_input",
        "values_match",
        "find_input",
        "connected_output",
    )
    missing = [
        name for name in required_controller
        if not callable(getattr(controller, name, None))
    ]
    missing.extend(
        name for name in required_animation
        if not callable(getattr(animation, name, None))
    )
    required_base = (
        "direct_call",
        "find_timeline",
        "find_item_by_name",
        "project_timeline_snapshot",
        "timeline_name",
        "timeline_unique_id",
    )
    missing.extend(
        f"base.{name}" for name in required_base
        if not callable(getattr(base, name, None))
    )
    if missing:
        raise RuntimeError("runtime_helpers_missing:" + ",".join(sorted(missing)))
    return base, controller, animation


def source_caption_snapshot(controller: Any, timeline: Any) -> Dict[str, Any]:
    rows = []
    track_count = int(controller.get_track_count(timeline, "video") or 0)
    for track_index in range(1, track_count + 1):
        for item in list(controller.get_track_items(timeline, "video", track_index) or []):
            name = str(controller.timeline_item_name(item) or "")
            if not name.startswith(PROTECTED_CAPTION_PREFIX):
                continue
            duration = None
            try:
                duration = item.GetDuration()
            except BaseException:
                duration = (
                    int(controller.timeline_item_end(item) or 0)
                    - int(controller.timeline_item_start(item) or 0)
                )
            comp_count = None
            try:
                comp_count = item.GetFusionCompCount()
            except BaseException:
                comp_count = None
            rows.append(
                {
                    "name": name,
                    "unique_id": controller.timeline_item_unique_id(item),
                    "track_index": track_index,
                    "start": controller.timeline_item_start(item),
                    "end": controller.timeline_item_end(item),
                    "duration": duration,
                    "fusion_comp_count": comp_count,
                }
            )
    rows.sort(
        key=lambda row: (
            int(row.get("track_index") or 0),
            int(row.get("start") or 0),
            str(row.get("name") or ""),
        )
    )
    return {
        "timeline_name": str(timeline.GetName() or ""),
        "timeline_unique_id": str(timeline.GetUniqueId() or ""),
        "caption_count": len(rows),
        "rows": rows,
    }


def lock_guard_ok(guard: Dict[str, Any], target_track: int) -> bool:
    during = (guard or {}).get("lock_snapshot_during") or {}
    video = during.get("video") or {}
    audio = during.get("audio") or {}
    if not video or target_track not in video:
        return False
    for index, locked in video.items():
        expected = int(index) != int(target_track)
        if locked is not expected:
            return False
    return all(locked is True for locked in audio.values())


def read_probe_state(
    controller: Any,
    animation: Any,
    item: Any,
) -> Dict[str, Any]:
    comp, text_tool, tool_info = controller.get_or_create_existing_title_text_tool(
        item,
        allow_add_fusion_comp=False,
    )
    if comp is None or text_tool is None:
        return {
            "ok": False,
            "tool_info": json_safe(tool_info),
            "error": "textplus_handle",
        }
    text_read = controller.try_read_fusion_input(text_tool, "StyledText")
    center_0 = animation.read_input(text_tool, "Center", 0)
    center_3 = animation.read_input(text_tool, "Center", 3)
    input_object = animation.find_input(text_tool, "Center")
    modifier_connected = animation.connected_output(input_object) is not None
    text_ok = bool(text_read.get("ok")) and controller.fusion_input_values_equivalent(
        PROBE_TEXT,
        text_read.get("value"),
    )
    frame_0_ok = animation.values_match("Center", center_0, CENTER_FRAME_0)
    frame_3_ok = animation.values_match("Center", center_3, CENTER_FRAME_3)
    return {
        "ok": bool(text_ok and frame_0_ok and frame_3_ok and modifier_connected),
        "tool_info": json_safe(tool_info),
        "text": json_safe(text_read),
        "center_frame_0": json_safe(center_0),
        "center_frame_3": json_safe(center_3),
        "text_ok": text_ok,
        "frame_0_ok": frame_0_ok,
        "frame_3_ok": frame_3_ok,
        "modifier_connected": modifier_connected,
    }


def final_report_markdown(report: Dict[str, Any]) -> str:
    outcome = "PASS" if report.get("ok") else "FAIL"
    provisioning = report.get("provisioning") or {}
    creation = provisioning.get("creation") or {}
    lines = [
        f"# {TASK_ID}",
        "",
        f"## Result\n\n{outcome}",
        "",
        "## Evidence",
        "",
        f"- Run ID: `{report.get('run_id')}`",
        f"- Command state result: `{'completed' if report.get('ok') else 'failed'}`",
        f"- Backend: `{report.get('carrier_backend')}`",
        f"- Edit page active: `{report.get('edit_page_active')}`",
        f"- Protected source captions before: `{report.get('protected_caption_count_before')}`",
        f"- Production call returned item: `{creation.get('returned_truthy')}`",
        f"- New item count: `{creation.get('new_item_count')}`",
        f"- Detection: `{creation.get('detected_by')}`",
        f"- Text readback: `{report.get('text_readback_ok')}`",
        f"- Center modifier connected: `{report.get('modifier_connected')}`",
        f"- Frame 0 keyframe: `{report.get('frame_0_readback_ok')}`",
        f"- Frame 3 keyframe: `{report.get('frame_3_readback_ok')}`",
        f"- Disposable duplicate deleted: `{report.get('temporary_timeline_deleted')}`",
        f"- Original timeline restored: `{report.get('original_timeline_restored')}`",
        f"- Original Resolve page restored: `{report.get('original_page_restored')}`",
        f"- Protected source unchanged: `{report.get('protected_source_unchanged')}`",
        f"- Accepted state unchanged: `{report.get('accepted_state_unchanged')}`",
        f"- Save calls: `{report.get('save_call_count')}`",
    ]
    errors = provisioning.get("errors") or []
    if errors:
        lines.extend(["", "## Provisioning errors", ""])
        lines.extend(f"- `{value}`" for value in errors)
    if report.get("failures"):
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- `{value}`" for value in report["failures"])
    return "\n".join(lines) + "\n"


def run(resolve: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    root = repository_root()
    command = context.get("command") if isinstance(context, dict) else None
    run_id = context.get("run_id") if isinstance(context, dict) else None
    if not isinstance(command, dict) or not isinstance(run_id, str) or not run_id:
        raise ValueError("bridge_context")
    if command.get("task_id") != TASK_ID or command.get("mode") != MODE:
        raise ValueError("command_identity")

    report_dir = resolve_inside_root(root, command.get("artifacts_dir"), "artifacts_dir")
    report_dir.mkdir(parents=True, exist_ok=True)
    accepted_path = root / ACCEPTED_STATE_RELATIVE_PATH
    accepted_before = raw_sha256(accepted_path)
    if accepted_before != command.get("accepted_state_sha256"):
        raise ValueError("accepted_state_baseline")

    source_contract = verify_source_contract(root, command)
    write_json(report_dir / "source_contract_verification.json", source_contract)

    report: Dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "mode": MODE,
        "run_id": run_id,
        "ok": False,
        "started_at": utc_now(),
        "carrier_backend": None,
        "source_contract_verified_count": source_contract["verified_count"],
        "edit_page_active": False,
        "protected_caption_count_before": 0,
        "text_readback_ok": False,
        "modifier_connected": False,
        "frame_0_readback_ok": False,
        "frame_3_readback_ok": False,
        "temporary_timeline_created": False,
        "temporary_timeline_deleted": False,
        "original_timeline_restored": False,
        "original_page_restored": False,
        "protected_source_unchanged": False,
        "accepted_state_unchanged": False,
        "save_call_count": 0,
        "provisioning": {},
        "cleanup": {},
        "failures": [],
    }

    base = controller = animation = None
    project_manager = project = media_pool = None
    original_timeline = source_timeline = duplicate = None
    original_name = original_unique_id = original_page = None
    source_before = None
    guard = None
    cleanup_finished = False
    probe = command.get("probe") or {}
    duplicate_name = str(probe.get("timeline_name") or "")
    item_name = str(probe.get("item_name") or "")

    def save_project(stage: str) -> Dict[str, Any]:
        value, row = base.direct_call(project_manager, "SaveProject")
        row["stage"] = stage
        row["success"] = bool(value)
        if value:
            report["save_call_count"] += 1
        return row

    try:
        if not duplicate_name.startswith("VC_STEP3D_TEXTPLUS_V2_"):
            raise ValueError("probe_timeline_name")
        if not item_name.startswith("VC_STEP3D_TEXTPLUS_V2_ITEM_"):
            raise ValueError("probe_item_name")

        base, controller, animation = load_runtime(root)
        project_manager, pm_row = base.direct_call(resolve, "GetProjectManager")
        project, project_row = base.direct_call(project_manager, "GetCurrentProject")
        media_pool, pool_row = base.direct_call(project, "GetMediaPool")
        original_timeline, current_row = base.direct_call(project, "GetCurrentTimeline")
        if project_manager is None or project is None or media_pool is None:
            raise RuntimeError("resolve_context")
        if original_timeline is None:
            raise RuntimeError("current_timeline")

        original_name = base.timeline_name(original_timeline)
        original_unique_id = base.timeline_unique_id(original_timeline)
        original_page, page_row = base.direct_call(resolve, "GetCurrentPage")
        before_timelines = base.project_timeline_snapshot(project)
        if base.find_timeline(project, duplicate_name) is not None:
            raise RuntimeError("probe_timeline_collision")

        source_timeline = base.find_timeline(project, PROTECTED_SOURCE_TIMELINE)
        if source_timeline is None:
            raise RuntimeError("protected_source_timeline")
        source_before = source_caption_snapshot(controller, source_timeline)
        report["protected_caption_count_before"] = source_before["caption_count"]
        if source_before["caption_count"] != PROTECTED_CAPTION_COUNT:
            raise RuntimeError(
                f"protected_caption_count:{source_before['caption_count']}"
            )

        preflight = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "checked_at": utc_now(),
            "project_manager": pm_row,
            "project": project_row,
            "media_pool": pool_row,
            "current_timeline": current_row,
            "current_page": page_row,
            "before_timelines": before_timelines,
            "original_timeline": {
                "name": original_name,
                "unique_id": original_unique_id,
            },
            "protected_source": source_before,
            "probe": probe,
            "accepted_state_sha256": accepted_before,
            "source_contract": source_contract,
        }
        write_json(report_dir / "probe_preflight.json", preflight)

        duplicate_value, duplicate_call = base.direct_call(
            source_timeline,
            "DuplicateTimeline",
            duplicate_name,
        )
        duplicate = (
            duplicate_value
            if duplicate_value is not None
            else base.find_timeline(project, duplicate_name)
        )
        if duplicate is None:
            raise RuntimeError("duplicate_timeline")
        report["temporary_timeline_created"] = True

        selected, select_call = base.direct_call(
            project,
            "SetCurrentTimeline",
            duplicate,
        )
        if not selected:
            raise RuntimeError("select_duplicate")
        _, edit_call = base.direct_call(resolve, "OpenPage", "edit")
        time.sleep(0.25)
        duplicate = base.find_timeline(project, duplicate_name)
        if duplicate is None:
            raise RuntimeError("duplicate_after_edit_page")
        selected_again, select_again_call = base.direct_call(
            project,
            "SetCurrentTimeline",
            duplicate,
        )
        current_page, current_page_call = base.direct_call(resolve, "GetCurrentPage")
        report["edit_page_active"] = bool(
            selected_again and str(current_page or "").casefold() == "edit"
        )
        if not report["edit_page_active"]:
            raise RuntimeError("edit_page_context")

        track_setup = controller.ensure_video_track(duplicate, TARGET_TRACK)
        if not track_setup.get("ok"):
            raise RuntimeError("target_track_create")
        track_name = controller.set_track_name_best_effort(
            duplicate,
            "video",
            TARGET_TRACK,
            "VC_STEP3D_TEXTPLUS_PROBE_V5",
        )
        existing_target_items = list(
            controller.get_track_items(duplicate, "video", TARGET_TRACK) or []
        )
        if existing_target_items:
            raise RuntimeError(
                f"target_track_not_empty:{len(existing_target_items)}"
            )
        guard = controller.apply_subtitle_track_guard(duplicate, TARGET_TRACK)
        if not lock_guard_ok(guard, TARGET_TRACK):
            raise RuntimeError("target_track_guard")

        duplicate_setup = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "duplicate_call": duplicate_call,
            "select_duplicate": select_call,
            "open_edit_page": edit_call,
            "select_duplicate_after_page": select_again_call,
            "current_page": current_page_call,
            "duplicate_name": base.timeline_name(duplicate),
            "duplicate_unique_id": base.timeline_unique_id(duplicate),
            "track_setup": json_safe(track_setup),
            "track_name": json_safe(track_name),
            "target_track_item_count_before": len(existing_target_items),
            "track_guard": json_safe(guard),
        }
        write_json(report_dir / "duplicate_timeline_setup.json", duplicate_setup)

        fps_value, fps_row = base.direct_call(
            duplicate,
            "GetSetting",
            "timelineFrameRate",
        )
        try:
            fps = float(fps_value or 24.0)
        except (TypeError, ValueError):
            fps = 24.0
        end_frame = TARGET_START_FRAME + PROBE_DURATION_FRAMES

        item, provisioning = controller.provision_textplus_fusion_composition(
            timeline=duplicate,
            start_frame=TARGET_START_FRAME,
            end_frame=end_frame,
            fps=fps,
            target_track=TARGET_TRACK,
            generated_name=item_name,
        )
        report["provisioning"] = json_safe(provisioning)
        report["carrier_backend"] = (
            provisioning.get("backend")
            if isinstance(provisioning, dict)
            else None
        )
        write_json(
            report_dir / "probe_provisioning.json",
            {
                "schema_version": 1,
                "task_id": TASK_ID,
                "run_id": run_id,
                "fps": fps,
                "fps_read": fps_row,
                "target_track": TARGET_TRACK,
                "start_frame": TARGET_START_FRAME,
                "end_frame": end_frame,
                "item_returned": item is not None,
                "provisioning": json_safe(provisioning),
            },
        )
        if (
            item is None
            or not isinstance(provisioning, dict)
            or provisioning.get("ok") is not True
        ):
            errors = (
                provisioning.get("errors")
                if isinstance(provisioning, dict)
                else None
            ) or ["unknown"]
            raise RuntimeError(
                "fusion_composition_provisioning:" + "|".join(map(str, errors))
            )

        comp, text_tool, tool_info = (
            controller.get_or_create_existing_title_text_tool(
                item,
                allow_add_fusion_comp=False,
            )
        )
        if comp is None or text_tool is None:
            raise RuntimeError("created_textplus_handle")

        text_write = controller.set_fusion_input_best_effort(
            text_tool,
            "StyledText",
            PROBE_TEXT,
        )
        center_write = controller.set_fusion_input_best_effort(
            text_tool,
            "Center",
            CENTER_FRAME_0,
        )
        modifier = animation.ensure_modifier(comp, text_tool, "Center")
        key_0_write = animation.write_key(
            text_tool,
            "Center",
            0,
            CENTER_FRAME_0,
        )
        key_3_write = animation.write_key(
            text_tool,
            "Center",
            3,
            CENTER_FRAME_3,
        )
        immediate_state = read_probe_state(controller, animation, item)
        if (
            not text_write.get("ok")
            or not center_write.get("ok")
            or not modifier.get("ok")
            or not key_0_write.get("ok")
            or not key_3_write.get("ok")
            or not immediate_state.get("ok")
        ):
            raise RuntimeError("immediate_textplus_readback")

        item_track = controller.timeline_item_track_info(item)
        item_start = controller.timeline_item_start(item)
        item_end = controller.timeline_item_end(item)
        creation = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "created_at": utc_now(),
            "item": {
                "name": controller.timeline_item_name(item),
                "unique_id": controller.timeline_item_unique_id(item),
                "track": json_safe(item_track),
                "start": item_start,
                "end": item_end,
            },
            "tool_info": json_safe(tool_info),
            "text_write": json_safe(text_write),
            "center_write": json_safe(center_write),
            "modifier": json_safe(modifier),
            "key_0_write": json_safe(key_0_write),
            "key_3_write": json_safe(key_3_write),
            "immediate_state": json_safe(immediate_state),
        }
        write_json(report_dir / "probe_creation.json", creation)

        first_save = save_project("persist_probe")
        if not first_save.get("success"):
            raise RuntimeError("save_probe")
        time.sleep(1.0)

        project, reacquire_project = base.direct_call(
            project_manager,
            "GetCurrentProject",
        )
        if project is None:
            raise RuntimeError("reacquire_project")
        media_pool, reacquire_pool = base.direct_call(project, "GetMediaPool")
        duplicate = base.find_timeline(project, duplicate_name)
        if media_pool is None or duplicate is None:
            raise RuntimeError("reacquire_probe_context")
        selected_after, selected_after_call = base.direct_call(
            project,
            "SetCurrentTimeline",
            duplicate,
        )
        if not selected_after:
            raise RuntimeError("reacquire_set_current")
        item_after, item_lookup = base.find_item_by_name(
            duplicate,
            controller,
            item_name,
        )
        if item_after is None:
            raise RuntimeError("reacquire_probe_item")

        persistent_state = read_probe_state(controller, animation, item_after)
        persistent_track = controller.timeline_item_track_info(item_after)
        persistent_start = controller.timeline_item_start(item_after)
        persistent_end = controller.timeline_item_end(item_after)
        track_ok = bool(
            persistent_track.get("track_type") == "video"
            and int(persistent_track.get("track_index") or 0) == TARGET_TRACK
        )
        range_ok = bool(
            persistent_start == TARGET_START_FRAME
            and persistent_end in {end_frame, end_frame - 1}
        )
        if not persistent_state.get("ok") or not track_ok or not range_ok:
            raise RuntimeError("persistent_probe_readback")

        report["text_readback_ok"] = bool(persistent_state.get("text_ok"))
        report["modifier_connected"] = bool(
            persistent_state.get("modifier_connected")
        )
        report["frame_0_readback_ok"] = bool(
            persistent_state.get("frame_0_ok")
        )
        report["frame_3_readback_ok"] = bool(
            persistent_state.get("frame_3_ok")
        )
        write_json(
            report_dir / "probe_persistent_readback.json",
            {
                "schema_version": 1,
                "task_id": TASK_ID,
                "run_id": run_id,
                "project_reacquire": reacquire_project,
                "media_pool_reacquire": reacquire_pool,
                "set_current": selected_after_call,
                "item_lookup": item_lookup,
                "item": {
                    "name": controller.timeline_item_name(item_after),
                    "unique_id": controller.timeline_item_unique_id(item_after),
                    "track": json_safe(persistent_track),
                    "start": persistent_start,
                    "end": persistent_end,
                    "track_ok": track_ok,
                    "range_ok": range_ok,
                },
                "state": json_safe(persistent_state),
                "first_save": first_save,
            },
        )

        if guard is not None:
            controller.restore_track_locks(duplicate, guard)
            guard = None
        original_after = base.find_timeline(
            project,
            original_name or "",
            original_unique_id,
        )
        if original_after is None:
            raise RuntimeError("restore_original_lookup")
        restored, restore_call = base.direct_call(
            project,
            "SetCurrentTimeline",
            original_after,
        )
        if not restored:
            raise RuntimeError("restore_original_timeline")
        report["original_timeline_restored"] = True
        deleted, delete_call = base.direct_call(
            media_pool,
            "DeleteTimelines",
            [duplicate],
        )
        if not deleted:
            raise RuntimeError("delete_probe_timeline")
        report["temporary_timeline_deleted"] = (
            base.find_timeline(project, duplicate_name) is None
        )
        if not report["temporary_timeline_deleted"]:
            raise RuntimeError("delete_probe_timeline_readback")

        if original_page:
            _, restore_page_call = base.direct_call(
                resolve,
                "OpenPage",
                original_page,
            )
        else:
            restore_page_call = {"skipped": True}
        page_after, page_after_call = base.direct_call(resolve, "GetCurrentPage")
        report["original_page_restored"] = bool(
            original_page is None or page_after == original_page
        )
        second_save = save_project("persist_cleanup")
        if not second_save.get("success"):
            raise RuntimeError("save_cleanup")

        source_after = base.find_timeline(project, PROTECTED_SOURCE_TIMELINE)
        source_after_snapshot = (
            source_caption_snapshot(controller, source_after)
            if source_after is not None
            else None
        )
        report["protected_source_unchanged"] = (
            source_after_snapshot == source_before
        )
        report["accepted_state_unchanged"] = (
            raw_sha256(accepted_path) == accepted_before
        )
        after_timelines = base.project_timeline_snapshot(project)
        report["original_timeline_restored"] = bool(
            after_timelines.get("current", {}).get("name") == original_name
            and (
                original_unique_id is None
                or after_timelines.get("current", {}).get("unique_id")
                == original_unique_id
            )
        )
        if after_timelines.get("count") != before_timelines.get("count"):
            raise RuntimeError("timeline_count_after_cleanup")
        if not report["original_timeline_restored"]:
            raise RuntimeError("original_timeline_after_cleanup")
        if not report["original_page_restored"]:
            raise RuntimeError("original_page_after_cleanup")
        if not report["protected_source_unchanged"]:
            raise RuntimeError("protected_source_changed")
        if not report["accepted_state_unchanged"]:
            raise RuntimeError("accepted_state_changed")

        cleanup = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "restore_original": restore_call,
            "delete_probe": delete_call,
            "restore_page": restore_page_call,
            "page_after": page_after_call,
            "second_save": second_save,
            "before_timelines": before_timelines,
            "after_timelines": after_timelines,
            "protected_source_before": source_before,
            "protected_source_after": source_after_snapshot,
            "protected_source_unchanged": report[
                "protected_source_unchanged"
            ],
            "accepted_state_unchanged": report[
                "accepted_state_unchanged"
            ],
        }
        report["cleanup"] = cleanup
        write_json(report_dir / "probe_cleanup.json", cleanup)
        cleanup_finished = True

        report["ok"] = bool(
            report["carrier_backend"]
            == "fusion_composition_explicit_textplus"
            and report["edit_page_active"]
            and report["text_readback_ok"]
            and report["modifier_connected"]
            and report["frame_0_readback_ok"]
            and report["frame_3_readback_ok"]
            and report["temporary_timeline_deleted"]
            and report["original_timeline_restored"]
            and report["original_page_restored"]
            and report["protected_source_unchanged"]
            and report["accepted_state_unchanged"]
            and report["save_call_count"] == 2
        )
        if not report["ok"]:
            report["failures"].append("acceptance_contract")

    except BaseException as exc:
        report["failures"].append(compact_exception(exc))
        report["traceback"] = traceback.format_exc()
    finally:
        if not cleanup_finished and base is not None:
            cleanup: Dict[str, Any] = {
                "attempted": True,
                "started_at": utc_now(),
                "errors": [],
            }
            try:
                if project_manager is not None:
                    project_after, row = base.direct_call(
                        project_manager,
                        "GetCurrentProject",
                    )
                    cleanup["project_reacquire"] = row
                    if project_after is not None:
                        project = project_after
                if project is not None:
                    media_pool_after, row = base.direct_call(
                        project,
                        "GetMediaPool",
                    )
                    cleanup["media_pool_reacquire"] = row
                    if media_pool_after is not None:
                        media_pool = media_pool_after
                duplicate_after = (
                    base.find_timeline(project, duplicate_name)
                    if project is not None and duplicate_name
                    else None
                )
                if (
                    guard is not None
                    and duplicate_after is not None
                    and controller is not None
                ):
                    cleanup["restore_track_locks"] = json_safe(
                        controller.restore_track_locks(
                            duplicate_after,
                            guard,
                        )
                    )
                original_after = (
                    base.find_timeline(
                        project,
                        original_name or "",
                        original_unique_id,
                    )
                    if project is not None
                    else None
                )
                if original_after is not None:
                    restored, row = base.direct_call(
                        project,
                        "SetCurrentTimeline",
                        original_after,
                    )
                    cleanup["restore_original"] = row
                    report["original_timeline_restored"] = bool(restored)
                duplicate_after = (
                    base.find_timeline(project, duplicate_name)
                    if project is not None and duplicate_name
                    else None
                )
                cleanup["probe_found"] = duplicate_after is not None
                if duplicate_after is not None and media_pool is not None:
                    deleted, row = base.direct_call(
                        media_pool,
                        "DeleteTimelines",
                        [duplicate_after],
                    )
                    cleanup["delete_probe"] = row
                    if not deleted:
                        cleanup["errors"].append("delete_probe")
                report["temporary_timeline_deleted"] = bool(
                    project is not None
                    and base.find_timeline(project, duplicate_name) is None
                )
                if original_page and resolve is not None:
                    _, row = base.direct_call(
                        resolve,
                        "OpenPage",
                        original_page,
                    )
                    cleanup["restore_page"] = row
                if resolve is not None:
                    page_after, row = base.direct_call(
                        resolve,
                        "GetCurrentPage",
                    )
                    cleanup["page_after"] = row
                    report["original_page_restored"] = bool(
                        original_page is None or page_after == original_page
                    )
                if project_manager is not None:
                    saved, row = base.direct_call(
                        project_manager,
                        "SaveProject",
                    )
                    row["stage"] = "failure_cleanup"
                    cleanup["save_cleanup"] = row
                    if saved:
                        report["save_call_count"] += 1
                    else:
                        cleanup["errors"].append("save_cleanup")
                source_after = (
                    base.find_timeline(project, PROTECTED_SOURCE_TIMELINE)
                    if project is not None
                    else None
                )
                source_after_snapshot = (
                    source_caption_snapshot(controller, source_after)
                    if source_after is not None and controller is not None
                    else None
                )
                cleanup["protected_source_after"] = source_after_snapshot
                report["protected_source_unchanged"] = bool(
                    source_before is not None
                    and source_after_snapshot == source_before
                )
                report["accepted_state_unchanged"] = bool(
                    accepted_path.is_file()
                    and raw_sha256(accepted_path) == accepted_before
                )
                cleanup["protected_source_unchanged"] = report[
                    "protected_source_unchanged"
                ]
                cleanup["accepted_state_unchanged"] = report[
                    "accepted_state_unchanged"
                ]
            except BaseException as cleanup_exc:
                cleanup["errors"].append(compact_exception(cleanup_exc))
                cleanup["traceback"] = traceback.format_exc()
            cleanup["finished_at"] = utc_now()
            cleanup["ok"] = bool(
                not cleanup["errors"]
                and report["temporary_timeline_deleted"]
                and report["original_timeline_restored"]
                and report["original_page_restored"]
                and report["protected_source_unchanged"]
                and report["accepted_state_unchanged"]
            )
            report["cleanup"] = cleanup
            write_json(report_dir / "probe_cleanup.json", cleanup)

        report["finished_at"] = utc_now()
        write_json(report_dir / "probe_result.json", report)
        write_json(report_dir / "report.json", report)
        write_text(report_dir / "FINAL_REPORT.md", final_report_markdown(report))

    return report
