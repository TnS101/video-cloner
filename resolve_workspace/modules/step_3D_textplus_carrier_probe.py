"""One-caption live Resolve probe for a genuine Fusion/TextPlus carrier.

The probe creates a temporary empty timeline, provisions one real Fusion
Composition with an explicit TextPlus node through the existing production
controller, writes text/position and one persistent Center keyframe, saves and
reacquires every Resolve handle for readback, then deletes the temporary
timeline and saves the clean project state.
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
from typing import Any, Dict, Iterable, Optional, Tuple

TASK_ID = "DZSQH7AUHJT_STEP_3D_TEXTPLUS_CARRIER_PROBE_V1"
MODE = "STEP_3D_TEXTPLUS_CARRIER_PROBE"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3D_textplus_carrier_probe.py"
CONTROLLER_RELATIVE_PATH = "resolve_workspace/resolve_apply_video_cloner_metadata.py"
ANIMATION_RELATIVE_PATH = "resolve_workspace/resolve_apply_caption_animation_step_3C.py"
BRIDGE_RELATIVE_PATH = "resolve_workspace/VC_Agent_Bridge.py"
ACCEPTED_STATE_RELATIVE_PATH = ".agent/state/latest_accepted.json"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
PROBE_TEXT = "VC_TEXTPLUS_CARRIER_PROBE"
STATIC_CENTER = [0.50, 0.50]
KEYFRAME_CENTER = [0.42, 0.58]
KEYFRAME_FRAME = 0
PROBE_DURATION_FRAMES = 48
PROBE_TRACK_INDEX = 1


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


def direct_call(obj: Any, method_name: str, *args: Any) -> Tuple[Any, Dict[str, Any]]:
    row: Dict[str, Any] = {
        "method": method_name,
        "available": bool(obj is not None and callable(getattr(obj, method_name, None))),
        "args": json_safe(args),
        "ok": False,
        "returned_type": None,
        "returned_repr": None,
        "error": None,
    }
    if not row["available"]:
        row["error"] = "method_missing"
        return None, row
    try:
        value = getattr(obj, method_name)(*args)
        row["returned_type"] = type(value).__name__ if value is not None else None
        row["returned_repr"] = repr(value)
        row["ok"] = value is not False and value is not None
        return value, row
    except BaseException as exc:
        row["error"] = compact_exception(exc)
        row["traceback"] = traceback.format_exc()
        return None, row


def load_module(path: Path, module_name: str, suppress_workspace_autorun: bool = False) -> Any:
    previous = os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN")
    if suppress_workspace_autorun:
        os.environ["VC_DISABLE_WORKSPACE_AUTORUN"] = "1"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"module_spec:{path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if suppress_workspace_autorun:
            if previous is None:
                os.environ.pop("VC_DISABLE_WORKSPACE_AUTORUN", None)
            else:
                os.environ["VC_DISABLE_WORKSPACE_AUTORUN"] = previous


def load_runtime_helpers(root: Path) -> Tuple[Any, Any]:
    controller = load_module(
        root / CONTROLLER_RELATIVE_PATH,
        "vc_textplus_probe_controller",
        suppress_workspace_autorun=False,
    )
    animation = load_module(
        root / ANIMATION_RELATIVE_PATH,
        "vc_textplus_probe_animation",
        suppress_workspace_autorun=True,
    )
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
    )
    required_animation = (
        "ensure_modifier",
        "write_key",
        "read_input",
        "find_input",
        "connected_output",
        "values_match",
    )
    missing = [name for name in required_controller if not callable(getattr(controller, name, None))]
    missing.extend(name for name in required_animation if not callable(getattr(animation, name, None)))
    if missing:
        raise RuntimeError("runtime_helpers_missing:" + ",".join(sorted(missing)))
    return controller, animation


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
    expected_paths = {
        MODULE_RELATIVE_PATH,
        CONTROLLER_RELATIVE_PATH,
        ANIMATION_RELATIVE_PATH,
        BRIDGE_RELATIVE_PATH,
    }
    if not isinstance(hashes, dict) or set(hashes) != expected_paths:
        raise ValueError("source_contract_paths")
    rows = []
    for relative in sorted(expected_paths):
        path = root / relative
        if not path.is_file():
            raise ValueError(f"source_contract_missing:{relative}")
        actual = normalized_sha256(path)
        expected = hashes.get(relative)
        matched = actual == expected
        rows.append({"path": relative, "expected": expected, "actual": actual, "matched": matched})
        if not matched:
            raise ValueError(f"source_contract_hash:{relative}")
    return {
        "version": 1,
        "algorithm": SOURCE_HASH_ALGORITHM,
        "verified_count": len(rows),
        "rows": rows,
    }


def timeline_name(timeline: Any) -> str:
    value, _ = direct_call(timeline, "GetName")
    return str(value or "")


def timeline_unique_id(timeline: Any) -> Optional[str]:
    value, _ = direct_call(timeline, "GetUniqueId")
    return str(value) if value else None


def project_timelines(project: Any) -> list[Any]:
    count_value, count_row = direct_call(project, "GetTimelineCount")
    if not count_row["ok"]:
        raise RuntimeError("timeline_count")
    count = int(count_value or 0)
    out = []
    for index in range(1, count + 1):
        timeline, row = direct_call(project, "GetTimelineByIndex", index)
        if row["ok"] and timeline is not None:
            out.append(timeline)
    return out


def project_timeline_snapshot(project: Any) -> Dict[str, Any]:
    rows = [
        {
            "name": timeline_name(timeline),
            "unique_id": timeline_unique_id(timeline),
        }
        for timeline in project_timelines(project)
    ]
    current, _ = direct_call(project, "GetCurrentTimeline")
    return {
        "count": len(rows),
        "timelines": rows,
        "current": {
            "name": timeline_name(current) if current is not None else None,
            "unique_id": timeline_unique_id(current) if current is not None else None,
        },
    }


def find_timeline(project: Any, name: str, unique_id: Optional[str] = None) -> Optional[Any]:
    matches = []
    for timeline in project_timelines(project):
        if unique_id and timeline_unique_id(timeline) == unique_id:
            return timeline
        if timeline_name(timeline) == name:
            matches.append(timeline)
    return matches[0] if len(matches) == 1 else None


def find_item_by_name(timeline: Any, controller: Any, name: str) -> Tuple[Optional[Any], Dict[str, Any]]:
    track_count_value, track_count_row = direct_call(timeline, "GetTrackCount", "video")
    if not track_count_row["ok"]:
        return None, {"ok": False, "error": "video_track_count", "call": track_count_row}
    matches = []
    rows = []
    for track_index in range(1, int(track_count_value or 0) + 1):
        items_value, items_row = direct_call(timeline, "GetItemListInTrack", "video", track_index)
        items = list(items_value or []) if items_row["ok"] else []
        for item in items:
            item_name = str(controller.timeline_item_name(item) or "")
            row = {
                "track_index": track_index,
                "name": item_name,
                "start": controller.timeline_item_start(item),
                "end": controller.timeline_item_end(item),
            }
            rows.append(row)
            if item_name == name:
                matches.append(item)
    return (
        matches[0] if len(matches) == 1 else None,
        {"ok": len(matches) == 1, "match_count": len(matches), "items": rows},
    )


def read_textplus_state(controller: Any, animation: Any, item: Any) -> Dict[str, Any]:
    comp, text_tool, info = controller.get_or_create_existing_title_text_tool(
        item,
        allow_add_fusion_comp=False,
    )
    if comp is None or text_tool is None:
        return {"ok": False, "tool_info": json_safe(info), "error": "textplus_handle"}
    text_read = controller.try_read_fusion_input(text_tool, "StyledText")
    center_static = controller.try_read_fusion_input(text_tool, "Center")
    center_at_key = animation.read_input(text_tool, "Center", KEYFRAME_FRAME)
    input_object = animation.find_input(text_tool, "Center")
    modifier_connected = animation.connected_output(input_object) is not None
    text_ok = bool(text_read.get("ok")) and controller.fusion_input_values_equivalent(
        PROBE_TEXT,
        text_read.get("value"),
    )
    center_ok = animation.values_match("Center", center_at_key, KEYFRAME_CENTER)
    return {
        "ok": bool(text_ok and center_ok and modifier_connected),
        "tool_info": json_safe(info),
        "text": json_safe(text_read),
        "center_static": json_safe(center_static),
        "center_at_keyframe": json_safe(center_at_key),
        "modifier_connected": modifier_connected,
        "text_ok": text_ok,
        "keyframe_value_ok": center_ok,
    }


def final_report_markdown(report: Dict[str, Any]) -> str:
    outcome = "PASS" if report.get("ok") else "FAIL"
    lines = [
        f"# {TASK_ID}",
        "",
        f"## Result\n\n{outcome}",
        "",
        "## Observable result",
        "",
        "Created one temporary Fusion Composition with an explicit TextPlus node, "
        "performed save/reacquire readback, and removed the temporary timeline.",
        "",
        "## Evidence",
        "",
        f"- Run ID: `{report.get('run_id')}`",
        f"- Probe backend: `{report.get('carrier_backend')}`",
        f"- Text readback: `{report.get('text_readback_ok')}`",
        f"- Center modifier connected: `{report.get('modifier_connected')}`",
        f"- Keyframe readback: `{report.get('keyframe_readback_ok')}`",
        f"- Temporary timeline deleted: `{report.get('temporary_timeline_deleted')}`",
        f"- Original timeline restored: `{report.get('original_timeline_restored')}`",
        f"- Save calls: `{report.get('save_call_count')}`",
        f"- Accepted-state unchanged: `{report.get('accepted_state_unchanged')}`",
    ]
    if report.get("failures"):
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- `{failure}`" for failure in report["failures"])
    return "\n".join(lines) + "\n"


def run(resolve: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    root = repository_root()
    command = context.get("command") if isinstance(context, dict) else None
    run_id = context.get("run_id") if isinstance(context, dict) else None
    if not isinstance(command, dict) or not isinstance(run_id, str) or not run_id:
        raise ValueError("bridge_context")
    if command.get("task_id") != TASK_ID:
        raise ValueError("command_task_id")
    if command.get("mode") != MODE:
        raise ValueError("command_mode")

    artifacts_dir = resolve_inside_root(root, command.get("artifacts_dir"), "artifacts_dir")
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    accepted_path = root / ACCEPTED_STATE_RELATIVE_PATH
    accepted_before = raw_sha256(accepted_path)
    if accepted_before != command.get("accepted_state_sha256"):
        raise ValueError("accepted_state_baseline")

    source_verification = verify_source_contract(root, command)
    write_json(artifacts_dir / "source_contract_verification.json", source_verification)

    report: Dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "mode": MODE,
        "run_id": run_id,
        "ok": False,
        "started_at": utc_now(),
        "carrier_backend": None,
        "source_contract_verified_count": source_verification["verified_count"],
        "save_call_count": 0,
        "temporary_timeline_created": False,
        "temporary_timeline_deleted": False,
        "original_timeline_restored": False,
        "accepted_state_unchanged": False,
        "text_readback_ok": False,
        "modifier_connected": False,
        "keyframe_readback_ok": False,
        "cleanup": {},
        "failures": [],
    }

    project_manager = None
    project = None
    media_pool = None
    original_timeline = None
    original_name = None
    original_unique_id = None
    probe_timeline = None
    probe_timeline_name = str((command.get("probe") or {}).get("timeline_name") or "")
    generated_name = str((command.get("probe") or {}).get("item_name") or "")
    cleanup_completed = False

    def save_project(stage_name: str) -> Dict[str, Any]:
        value, row = direct_call(project_manager, "SaveProject")
        row["stage"] = stage_name
        row["success"] = bool(value)
        if value:
            report["save_call_count"] += 1
        return row

    try:
        if not probe_timeline_name.startswith("VC_STEP3D_TEXTPLUS_PROBE_"):
            raise ValueError("probe_timeline_name")
        if not generated_name.startswith("VC_STEP3D_TEXTPLUS_ITEM_"):
            raise ValueError("probe_item_name")

        controller, animation = load_runtime_helpers(root)
        project_manager, pm_row = direct_call(resolve, "GetProjectManager")
        if project_manager is None:
            raise RuntimeError("project_manager")
        project, project_row = direct_call(project_manager, "GetCurrentProject")
        if project is None:
            raise RuntimeError("current_project")
        media_pool, media_pool_row = direct_call(project, "GetMediaPool")
        if media_pool is None:
            raise RuntimeError("media_pool")
        original_timeline, current_row = direct_call(project, "GetCurrentTimeline")
        if original_timeline is None:
            raise RuntimeError("current_timeline")
        original_name = timeline_name(original_timeline)
        original_unique_id = timeline_unique_id(original_timeline)
        before_snapshot = project_timeline_snapshot(project)
        if any(row["name"] == probe_timeline_name for row in before_snapshot["timelines"]):
            raise RuntimeError("probe_timeline_collision")

        preflight = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "checked_at": utc_now(),
            "project_manager": pm_row,
            "project": project_row,
            "media_pool": media_pool_row,
            "current_timeline": current_row,
            "before_snapshot": before_snapshot,
            "probe_timeline_name": probe_timeline_name,
            "generated_item_name": generated_name,
            "accepted_state_sha256": accepted_before,
            "source_contract": source_verification,
        }
        write_json(artifacts_dir / "probe_preflight.json", preflight)

        probe_timeline, create_row = direct_call(media_pool, "CreateEmptyTimeline", probe_timeline_name)
        if probe_timeline is None:
            raise RuntimeError("create_empty_timeline")
        report["temporary_timeline_created"] = True
        set_current_value, set_current_row = direct_call(project, "SetCurrentTimeline", probe_timeline)
        if not set_current_value:
            raise RuntimeError("set_probe_timeline_current")

        fps_value, fps_row = direct_call(probe_timeline, "GetSetting", "timelineFrameRate")
        if fps_value in (None, ""):
            fps_value, fps_row = direct_call(project, "GetSetting", "timelineFrameRate")
        try:
            fps = float(fps_value or 24.0)
        except (TypeError, ValueError):
            fps = 24.0

        start_value, start_row = direct_call(probe_timeline, "GetStartFrame")
        try:
            start_frame = int(start_value) if start_value is not None else 0
        except (TypeError, ValueError):
            start_frame = 0
        end_frame = start_frame + PROBE_DURATION_FRAMES

        item, provisioning = controller.provision_textplus_fusion_composition(
            timeline=probe_timeline,
            start_frame=start_frame,
            end_frame=end_frame,
            fps=fps,
            target_track=PROBE_TRACK_INDEX,
            generated_name=generated_name,
        )
        report["carrier_backend"] = provisioning.get("backend") if isinstance(provisioning, dict) else None
        if item is None or not isinstance(provisioning, dict) or not provisioning.get("ok"):
            raise RuntimeError("fusion_composition_provisioning")

        comp, text_tool, tool_info = controller.get_or_create_existing_title_text_tool(
            item,
            allow_add_fusion_comp=False,
        )
        if comp is None or text_tool is None:
            raise RuntimeError("created_textplus_handle")

        text_write = controller.set_fusion_input_best_effort(text_tool, "StyledText", PROBE_TEXT)
        center_write = controller.set_fusion_input_best_effort(text_tool, "Center", STATIC_CENTER)
        text_read = controller.try_read_fusion_input(text_tool, "StyledText")
        center_read = controller.try_read_fusion_input(text_tool, "Center")
        if not text_write.get("ok") or not text_read.get("ok") or not controller.fusion_input_values_equivalent(PROBE_TEXT, text_read.get("value")):
            raise RuntimeError("probe_text_write_readback")
        if not center_write.get("ok") or not center_read.get("ok") or not controller.fusion_input_values_equivalent(STATIC_CENTER, center_read.get("value")):
            raise RuntimeError("probe_center_write_readback")

        modifier = animation.ensure_modifier(comp, text_tool, "Center")
        if not modifier.get("ok"):
            raise RuntimeError("probe_center_modifier")
        key_write = animation.write_key(text_tool, "Center", KEYFRAME_FRAME, KEYFRAME_CENTER)
        key_read = animation.read_input(text_tool, "Center", KEYFRAME_FRAME)
        key_ok = animation.values_match("Center", key_read, KEYFRAME_CENTER)
        modifier_connected = animation.connected_output(animation.find_input(text_tool, "Center")) is not None
        if not key_write.get("ok") or not key_ok or not modifier_connected:
            raise RuntimeError("probe_center_keyframe")

        creation = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "created_at": utc_now(),
            "timeline_create": create_row,
            "set_current": set_current_row,
            "fps": fps,
            "fps_read": fps_row,
            "start_frame": start_frame,
            "start_frame_read": start_row,
            "end_frame": end_frame,
            "target_track": PROBE_TRACK_INDEX,
            "provisioning": json_safe(provisioning),
            "tool_info": json_safe(tool_info),
            "text_write": json_safe(text_write),
            "text_read": json_safe(text_read),
            "center_write": json_safe(center_write),
            "center_read": json_safe(center_read),
            "modifier": json_safe(modifier),
            "key_write": json_safe(key_write),
            "key_read": json_safe(key_read),
            "modifier_connected": modifier_connected,
        }
        write_json(artifacts_dir / "probe_creation.json", creation)

        first_save = save_project("persist_probe")
        if not first_save.get("success"):
            raise RuntimeError("save_probe")
        time.sleep(1.0)

        project_after, project_after_row = direct_call(project_manager, "GetCurrentProject")
        if project_after is None:
            raise RuntimeError("reacquire_project")
        project = project_after
        media_pool, media_pool_after_row = direct_call(project, "GetMediaPool")
        if media_pool is None:
            raise RuntimeError("reacquire_media_pool")
        probe_after = find_timeline(project, probe_timeline_name)
        if probe_after is None:
            raise RuntimeError("reacquire_probe_timeline")
        probe_timeline = probe_after
        set_after_value, set_after_row = direct_call(project, "SetCurrentTimeline", probe_after)
        if not set_after_value:
            raise RuntimeError("reacquire_set_current")
        item_after, item_lookup = find_item_by_name(probe_after, controller, generated_name)
        if item_after is None:
            raise RuntimeError("reacquire_probe_item")

        state = read_textplus_state(controller, animation, item_after)
        track_info = controller.timeline_item_track_info(item_after)
        actual_start = controller.timeline_item_start(item_after)
        actual_end = controller.timeline_item_end(item_after)
        track_ok = (
            track_info.get("track_type") == "video"
            and int(track_info.get("track_index") or 0) == PROBE_TRACK_INDEX
        )
        range_ok = actual_start == start_frame and actual_end in {end_frame, end_frame - 1}
        if not state.get("ok") or not track_ok or not range_ok:
            raise RuntimeError("persistent_probe_readback")

        report["text_readback_ok"] = bool(state.get("text_ok"))
        report["modifier_connected"] = bool(state.get("modifier_connected"))
        report["keyframe_readback_ok"] = bool(state.get("keyframe_value_ok"))
        readback = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "read_at": utc_now(),
            "project_reacquire": project_after_row,
            "media_pool_reacquire": media_pool_after_row,
            "set_current": set_after_row,
            "item_lookup": item_lookup,
            "item": {
                "name": controller.timeline_item_name(item_after),
                "track": json_safe(track_info),
                "start": actual_start,
                "end": actual_end,
                "track_ok": track_ok,
                "range_ok": range_ok,
            },
            "textplus": json_safe(state),
            "first_save": first_save,
        }
        write_json(artifacts_dir / "probe_persistent_readback.json", readback)

        original_after = find_timeline(project, original_name or "", original_unique_id)
        if original_after is None:
            raise RuntimeError("restore_original_timeline_lookup")
        restored_value, restored_row = direct_call(project, "SetCurrentTimeline", original_after)
        if not restored_value:
            raise RuntimeError("restore_original_timeline")
        report["original_timeline_restored"] = True

        delete_value, delete_row = direct_call(media_pool, "DeleteTimelines", [probe_after])
        if not delete_value:
            raise RuntimeError("delete_probe_timeline")
        report["temporary_timeline_deleted"] = find_timeline(project, probe_timeline_name) is None
        if not report["temporary_timeline_deleted"]:
            raise RuntimeError("delete_probe_timeline_readback")

        second_save = save_project("persist_cleanup")
        if not second_save.get("success"):
            raise RuntimeError("save_cleanup")
        after_snapshot = project_timeline_snapshot(project)
        report["original_timeline_restored"] = bool(
            after_snapshot.get("current", {}).get("name") == original_name
            and (
                original_unique_id is None
                or after_snapshot.get("current", {}).get("unique_id") == original_unique_id
            )
        )
        if after_snapshot.get("count") != before_snapshot.get("count"):
            raise RuntimeError("timeline_count_after_cleanup")
        if not report["original_timeline_restored"]:
            raise RuntimeError("original_timeline_after_cleanup")

        accepted_after = raw_sha256(accepted_path)
        report["accepted_state_unchanged"] = accepted_after == accepted_before
        if not report["accepted_state_unchanged"]:
            raise RuntimeError("accepted_state_changed")

        cleanup = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "cleaned_at": utc_now(),
            "restore_original": restored_row,
            "delete_timeline": delete_row,
            "second_save": second_save,
            "before_snapshot": before_snapshot,
            "after_snapshot": after_snapshot,
            "accepted_state_before": accepted_before,
            "accepted_state_after": accepted_after,
            "accepted_state_unchanged": report["accepted_state_unchanged"],
        }
        report["cleanup"] = cleanup
        write_json(artifacts_dir / "probe_cleanup.json", cleanup)
        cleanup_completed = True

        report["ok"] = bool(
            report["temporary_timeline_deleted"]
            and report["original_timeline_restored"]
            and report["accepted_state_unchanged"]
            and report["text_readback_ok"]
            and report["modifier_connected"]
            and report["keyframe_readback_ok"]
            and report["save_call_count"] == 2
            and report["carrier_backend"] == "fusion_composition_explicit_textplus"
        )
        if not report["ok"]:
            report["failures"].append("acceptance_contract")

    except BaseException as exc:
        report["failures"].append(compact_exception(exc))
        report["traceback"] = traceback.format_exc()
    finally:
        if not cleanup_completed and project is not None and media_pool is not None:
            cleanup_attempts: Dict[str, Any] = {
                "attempted": True,
                "started_at": utc_now(),
                "restore_original": None,
                "probe_lookup": None,
                "delete_timeline": None,
                "save_cleanup": None,
                "accepted_state_unchanged": None,
                "errors": [],
            }
            try:
                original_after = find_timeline(project, original_name or "", original_unique_id)
                if original_after is not None:
                    _, cleanup_attempts["restore_original"] = direct_call(
                        project,
                        "SetCurrentTimeline",
                        original_after,
                    )
                    report["original_timeline_restored"] = bool(
                        cleanup_attempts["restore_original"].get("ok")
                    )
                probe_after = find_timeline(project, probe_timeline_name) if probe_timeline_name else None
                cleanup_attempts["probe_lookup"] = {
                    "found": probe_after is not None,
                    "name": probe_timeline_name,
                }
                if probe_after is not None:
                    deleted, cleanup_attempts["delete_timeline"] = direct_call(
                        media_pool,
                        "DeleteTimelines",
                        [probe_after],
                    )
                    report["temporary_timeline_deleted"] = bool(deleted) and find_timeline(
                        project,
                        probe_timeline_name,
                    ) is None
                    if deleted:
                        cleanup_attempts["save_cleanup"] = save_project("failure_cleanup")
                else:
                    report["temporary_timeline_deleted"] = bool(report["temporary_timeline_created"])
                cleanup_attempts["accepted_state_unchanged"] = raw_sha256(accepted_path) == accepted_before
                report["accepted_state_unchanged"] = bool(cleanup_attempts["accepted_state_unchanged"])
            except BaseException as cleanup_exc:
                cleanup_attempts["errors"].append(compact_exception(cleanup_exc))
                cleanup_attempts["traceback"] = traceback.format_exc()
            cleanup_attempts["finished_at"] = utc_now()
            report["cleanup"] = cleanup_attempts
            try:
                write_json(artifacts_dir / "probe_cleanup.json", cleanup_attempts)
            except BaseException:
                pass

        report["finished_at"] = utc_now()
        report["ok"] = bool(report.get("ok") and not report.get("failures"))
        try:
            write_json(artifacts_dir / "probe_result.json", report)
            write_text(artifacts_dir / "FINAL_REPORT.md", final_report_markdown(report))
        except BaseException:
            report["failures"].append("result_artifact_write_failed")
            report["ok"] = False

    return report
