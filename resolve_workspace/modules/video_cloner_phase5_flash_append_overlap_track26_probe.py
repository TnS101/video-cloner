"""Disposable Resolve probe for track-26 same-range append behavior."""
from __future__ import annotations

import importlib.util
import json
import os
import traceback
from pathlib import Path
from typing import Any, Mapping

TASK_ID = "VIDEO_CLONER_PHASE5_FLASH_APPEND_OVERLAP_TRACK26_PROBE_V1"
MODE = "phase5_flash_append_overlap_track26_probe"
PROJECT_NAME = "New Project 1"
REEL1 = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1_occlusion_complete_v4_flash_transition_v4"
REEL2 = "DcJRJtUKScu_standalone_timeline"
TRACK = 26
START = 94
DURATION = 4
DECISIVE = {
    "SAME_TRACK_DESTINATION_OVERLAP_CONFIRMED",
    "TRACK26_EMPTY_APPEND_FAILED",
    "APPEND_HELPER_POST_API_CLASSIFICATION_DEFECT",
    "OVERLAP_APPEND_SUCCEEDED",
}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_dependencies(root: Path) -> tuple[Any, Any, Any]:
    modules = root / "resolve_workspace" / "modules"
    v4 = _load("vc_track26_probe_v4", modules / "advanced_transition_flash_neutral_rgba_v4.py")
    p4b = _load("vc_track26_probe_p4b", modules / "video_cloner_phase4b_timeline_application.py")
    return v4.V1, v4, p4b


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _timeline_uid(v1: Any, timeline: Any) -> str:
    return str(v1.safe_call(timeline, "GetUniqueId", default="") or "")


def _find_timeline(v1: Any, project: Any, name: str) -> Any:
    matches = []
    count = int(v1.safe_call(project, "GetTimelineCount", default=0) or 0)
    for index in range(1, count + 1):
        timeline = v1.safe_call(project, "GetTimelineByIndex", index, default=None)
        if timeline is not None and str(v1.safe_call(timeline, "GetName", default="") or "") == name:
            matches.append(timeline)
    return matches[0] if len(matches) == 1 else None


def _item_row(v1: Any, timeline: Any, track: int, item: Any) -> dict[str, Any]:
    media = v1.safe_call(item, "GetMediaPoolItem", default=None)
    return {
        "uid": v1.item_uid(item),
        "name": v1.item_name(item),
        "track_index": track,
        "start": v1.item_start(item),
        "end": v1.item_end(item),
        "duration": v1.item_duration(item),
        "has_media_pool_item": media is not None,
        "media_pool_item_name": str(v1.safe_call(media, "GetName", default="") or "") if media is not None else None,
    }


def track_inventory(v1: Any, timeline: Any) -> list[dict[str, Any]]:
    return [
        _item_row(v1, timeline, track, item)
        for track, item in v1.all_video_items(timeline)
        if track == TRACK
    ]


def _range_count(rows: list[dict[str, Any]]) -> int:
    return sum(
        row.get("track_index") == TRACK
        and row.get("start") == START
        and row.get("duration") == DURATION
        and row.get("has_media_pool_item") is True
        for row in rows
    )


def public_append(v1: Any, result: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {key: v1.json_safe(value) for key, value in result.items() if key != "assigned"}


def classify(
    first: Mapping[str, Any],
    second: Mapping[str, Any] | None,
    before: list[dict[str, Any]],
    after_first: list[dict[str, Any]],
    after_second: list[dict[str, Any]] | None,
) -> str:
    first_delta = _range_count(after_first) - _range_count(before)
    first_api = bool((first.get("call") or {}).get("ok")) or first_delta > 0
    if first.get("ok") is not True:
        return "APPEND_HELPER_POST_API_CLASSIFICATION_DEFECT" if first_api else "TRACK26_EMPTY_APPEND_FAILED"
    if first_delta != 1 or second is None or after_second is None:
        return "AMBIGUOUS_DIAGNOSTIC_STATE"
    second_delta = _range_count(after_second) - _range_count(after_first)
    second_api = bool((second.get("call") or {}).get("ok")) or second_delta > 0
    if second.get("ok") is not True:
        if second_api:
            return "APPEND_HELPER_POST_API_CLASSIFICATION_DEFECT"
        if second_delta == 0:
            return "SAME_TRACK_DESTINATION_OVERLAP_CONFIRMED"
        return "AMBIGUOUS_DIAGNOSTIC_STATE"
    return "OVERLAP_APPEND_SUCCEEDED" if second_delta == 1 else "AMBIGUOUS_DIAGNOSTIC_STATE"


def execute(resolve: Any, context: Mapping[str, Any], dependencies: tuple[Any, Any, Any] | None = None) -> dict[str, Any]:
    command = context.get("command") or {}
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    report: dict[str, Any] = {
        "ok": False,
        "task_id": TASK_ID,
        "mode": MODE,
        "run_id": run_id,
        "classification": "AMBIGUOUS_DIAGNOSTIC_STATE",
        "probe_classification": "AMBIGUOUS_DIAGNOSTIC_STATE",
        "save_project_count": 0,
        "failures": [],
    }
    root = repository_root()
    report_dir = root / ".agent" / "reports" / TASK_ID / run_id
    v1 = v4 = p4b = None
    manager = project = media_pool = previous = disposable = None
    ownership = None
    disposable_name = str((command.get("payload") or {}).get("disposable_timeline_name") or "")
    protected_before = None
    evidence: dict[str, Any] = {}
    cleanup: dict[str, Any] = {"attempted": False, "safe": False, "errors": []}
    try:
        if command.get("task_id") != TASK_ID or command.get("mode") != MODE or not run_id:
            raise ValueError("command_identity")
        payload = command.get("payload") or {}
        if payload.get("expected_project") != PROJECT_NAME or payload.get("track_index") != TRACK:
            raise ValueError("probe_contract")
        if payload.get("record_frame") != START or payload.get("duration_frames") != DURATION:
            raise ValueError("probe_range")
        if not disposable_name.startswith("VC_PHASE5_TRACK26_PROBE_"):
            raise ValueError("disposable_timeline_name")
        v1, v4, p4b = dependencies or load_dependencies(root)
        report_dir = v1.relative_path(root, command.get("report_path")).parent
        report["source_contract"] = v1.verify_source_contract(root, command)
        manager = v1.safe_call(resolve, "GetProjectManager", default=None)
        project = v1.safe_call(manager, "GetCurrentProject", default=None)
        if project is None or v1.safe_call(project, "GetName", default="") != PROJECT_NAME:
            raise RuntimeError("project_identity")
        media_pool = v1.safe_call(project, "GetMediaPool", default=None)
        previous = v1.safe_call(project, "GetCurrentTimeline", default=None)
        if media_pool is None or previous is None:
            raise RuntimeError("project_handles")
        protected_before = p4b.timeline_inventory(project)
        names = [row.get("name") for row in protected_before]
        if names.count(REEL1) != 1 or names.count(REEL2) != 1 or _find_timeline(v1, project, disposable_name) is not None:
            raise RuntimeError("protected_prestate")
        report["protected_inventory_before"] = protected_before
        report["previous_current_timeline"] = {
            "name": p4b.timeline_name(previous),
            "unique_id": _timeline_uid(v1, previous),
        }

        disposable, create_call = v1.direct_call(media_pool, "CreateEmptyTimeline", disposable_name)
        evidence["timeline_create"] = create_call
        if disposable is None:
            raise RuntimeError("disposable_create")
        selected = bool(v1.safe_call(project, "SetCurrentTimeline", disposable, default=False))
        evidence["timeline_selected"] = {
            "set_ok": selected,
            "readback": p4b.timeline_name(v1.safe_call(project, "GetCurrentTimeline", default=None)),
        }
        if not selected or evidence["timeline_selected"]["readback"] != disposable_name:
            raise RuntimeError("disposable_selection")
        track_calls = []
        while v1.track_count(disposable, "video") < TRACK:
            _, call = v1.direct_call(disposable, "AddTrack", "video")
            track_calls.append(call)
            if not call.get("ok"):
                break
        evidence["track_provisioning"] = {
            "calls": track_calls,
            "final_video_track_count": v1.track_count(disposable, "video"),
        }
        if evidence["track_provisioning"]["final_video_track_count"] < TRACK:
            raise RuntimeError("track26_provisioning")

        assets = v4.validate_neutral_assets(root)
        ownership = v4.import_neutral_carrier(media_pool, root, assets)
        evidence["neutral_assets"] = v1.json_safe(assets)
        evidence["media_ownership"] = {key: v1.json_safe(value) for key, value in ownership.items() if key != "item"}
        if ownership.get("ok") is not True or ownership.get("item") is None:
            raise RuntimeError("neutral_media")

        spec1 = [{"name": "VC_TRACK26_PROBE_FIRST", "start_frame": START, "duration_frames": DURATION}]
        spec2 = [{"name": "VC_TRACK26_PROBE_OVERLAP", "start_frame": START, "duration_frames": DURATION}]
        before = track_inventory(v1, disposable)
        first = v1.append_flash_carriers(media_pool, disposable, {"media_pool_item": ownership["item"], "source_start": 0}, spec1, TRACK)
        after_first = track_inventory(v1, disposable)
        evidence.update({"before_first": before, "first_append": public_append(v1, first), "after_first": after_first})
        write_json(report_dir / "probe_append_evidence.json", v1.json_safe(evidence))
        second = None
        after_second = None
        if first.get("ok") is True and _range_count(after_first) - _range_count(before) == 1:
            second = v1.append_flash_carriers(media_pool, disposable, {"media_pool_item": ownership["item"], "source_start": 0}, spec2, TRACK)
            after_second = track_inventory(v1, disposable)
            evidence.update({"second_append": public_append(v1, second), "after_second": after_second})
            write_json(report_dir / "probe_append_evidence.json", v1.json_safe(evidence))
        report["probe_classification"] = classify(first, second, before, after_first, after_second)
        report["classification"] = report["probe_classification"]
        report["append_evidence"] = evidence
    except BaseException as exc:
        report["failures"].append(f"{type(exc).__name__}: {exc}")
        report["traceback"] = traceback.format_exc()
    finally:
        if v1 is not None and project is not None and media_pool is not None:
            cleanup["attempted"] = True
            previous_name = p4b.timeline_name(previous) if previous is not None else ""
            previous_uid = _timeline_uid(v1, previous) if previous is not None else ""
            restore_ok = False
            if previous is not None:
                set_ok = bool(v1.safe_call(project, "SetCurrentTimeline", previous, default=False))
                current = v1.safe_call(project, "GetCurrentTimeline", default=None)
                restore_ok = bool(set_ok and p4b.timeline_name(current) == previous_name and (not previous_uid or _timeline_uid(v1, current) == previous_uid))
            cleanup["previous_current_timeline_restored"] = restore_ok
            probe = _find_timeline(v1, project, disposable_name) if disposable_name else None
            if probe is not None:
                deleted, delete_call = v1.direct_call(media_pool, "DeleteTimelines", [probe])
                cleanup["timeline_delete"] = delete_call
                cleanup["disposable_timeline_deleted"] = bool(deleted and _find_timeline(v1, project, disposable_name) is None)
            else:
                cleanup["disposable_timeline_deleted"] = disposable is None
            protected_after = p4b.timeline_inventory(project)
            cleanup["protected_inventory_after"] = protected_after
            cleanup["protected_timelines_unchanged"] = protected_before is not None and protected_after == protected_before
            media_safe = bool(cleanup["disposable_timeline_deleted"] and cleanup["protected_timelines_unchanged"])
            if media_safe:
                cleanup["media_delete"] = v4._delete_owned_media_pool_item(media_pool, ownership)
            else:
                cleanup["media_delete"] = {"attempted": False, "ok": False, "error": "protected_dependency_or_timeline_cleanup_unproven"}
            if not restore_ok:
                cleanup["errors"].append("previous_current_timeline_restore")
            if not cleanup["disposable_timeline_deleted"]:
                cleanup["errors"].append("disposable_timeline_delete")
            if not cleanup["protected_timelines_unchanged"]:
                cleanup["errors"].append("protected_timeline_change")
            if not cleanup["media_delete"].get("ok"):
                cleanup["errors"].append("media_cleanup")
            cleanup["safe"] = not cleanup["errors"]
        else:
            cleanup["errors"].append("cleanup_handles_unavailable")
        report["cleanup"] = cleanup
        if not cleanup.get("safe"):
            report["classification"] = "AMBIGUOUS_CLEANUP_STATE"
        report["ok"] = bool(report["classification"] in DECISIVE and cleanup.get("safe") and not report["failures"])
        try:
            write_json(report_dir / "probe_cleanup_evidence.json", v1.json_safe(cleanup) if v1 is not None else cleanup)
        except BaseException:
            report["ok"] = False
            report["failures"].append("cleanup_evidence_write")
    return report


run = execute
