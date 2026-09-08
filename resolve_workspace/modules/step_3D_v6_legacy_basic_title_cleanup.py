"""Create a Text+-only review timeline from the accepted V6 rollout.

The accepted V6 timeline contains the 115 generated Text+ instances on V3-V7,
but it also preserves 116 legacy Basic Title items named ``Text`` on V2.  This
module duplicates V6, deletes only that exact V2 legacy set, and proves every
other timeline item remains structurally identical.

The accepted V6 timeline is never modified.  On PASS the cleaned duplicate is
retained for visual review.  On FAIL the duplicate is deleted and the original
Resolve timeline/page are restored.
"""
from __future__ import annotations

import importlib.util
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

ROLLOUT_PATH = Path(__file__).with_name("step_3D_full_lifecycle_textplus_rollout.py")
_spec = importlib.util.spec_from_file_location("vc_step_3d_rollout_v6", ROLLOUT_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot_load:{ROLLOUT_PATH}")
rollout = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rollout
_spec.loader.exec_module(rollout)
base = rollout.base

TASK_ID = "DZSQH7AUHJT_STEP_3D_V6_LEGACY_BASIC_TITLE_CLEANUP_V1"
MODE = "STEP_3D_V6_LEGACY_BASIC_TITLE_CLEANUP"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3D_v6_legacy_basic_title_cleanup.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_full_step_3D_complete_v6_exact_lifecycles"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_full_step_3D_complete_v6_textplus_only"
LEGACY_TRACK_INDEX = 2
LEGACY_ITEM_NAME = "Text"
EXPECTED_LEGACY_COUNT = 116
EXPECTED_TEXTPLUS_COUNT = 115
EXPECTED_TEXTPLUS_TRACK_USAGE = {3: 71, 4: 21, 5: 16, 6: 5, 7: 2}
TEXTPLUS_TRACKS = tuple(sorted(EXPECTED_TEXTPLUS_TRACK_USAGE))
EXPECTED_MATTE = {
    "name": "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052",
    "track_index": 4,
    "start": 429,
    "end": 434,
    "duration": 5,
    "media_pool_item_name": "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052",
}
ACCEPTED_STATE_RELATIVE_PATH = rollout.ACCEPTED_STATE_RELATIVE_PATH

STABLE_FIELDS = (
    "name",
    "track_index",
    "start",
    "end",
    "duration",
    "fusion_comp_count",
    "media_pool_item_name",
)


def stable_item_row(track: int, item: Any) -> Dict[str, Any]:
    summary = base.item_summary(int(track), item)
    return {field: summary.get(field) for field in STABLE_FIELDS}


def stable_timeline_rows(timeline: Any) -> List[Dict[str, Any]]:
    rows = [stable_item_row(track, item) for track, item in base.all_video_items(timeline)]
    return sorted(
        rows,
        key=lambda row: (
            int(row.get("track_index") or 0),
            int(row.get("start") or 0),
            int(row.get("end") or 0),
            str(row.get("name") or ""),
            str(row.get("media_pool_item_name") or ""),
        ),
    )


def is_legacy_basic_title(track: int, item: Any) -> bool:
    summary = base.item_summary(int(track), item)
    return bool(
        int(track) == LEGACY_TRACK_INDEX
        and summary.get("name") == LEGACY_ITEM_NAME
        and summary.get("media_pool_item_name") is None
    )


def legacy_basic_title_items(timeline: Any) -> List[Tuple[int, Any]]:
    return [
        (track, item)
        for track, item in base.all_video_items(timeline)
        if is_legacy_basic_title(track, item)
    ]


def track_items(timeline: Any, track_index: int) -> List[Any]:
    return [item for track, item in base.all_video_items(timeline) if int(track) == int(track_index)]


def textplus_inventory(timeline: Any) -> Dict[str, Any]:
    rows = []
    for track, item in base.all_video_items(timeline):
        name = base.item_name(item)
        if not name.startswith(base.CAPTION_PREFIX):
            continue
        summary = base.item_summary(track, item)
        rows.append(summary)
    usage = Counter(int(row.get("track_index") or 0) for row in rows)
    names = [str(row.get("name") or "") for row in rows]
    checks = {
        "count": len(rows) == EXPECTED_TEXTPLUS_COUNT,
        "unique_names": len(set(names)) == EXPECTED_TEXTPLUS_COUNT,
        "tracks": all(int(row.get("track_index") or 0) in TEXTPLUS_TRACKS for row in rows),
        "track_usage": dict(sorted(usage.items())) == EXPECTED_TEXTPLUS_TRACK_USAGE,
        "fusion_comp_count": all(int(row.get("fusion_comp_count") or 0) == 1 for row in rows),
        "media_backed": all(bool(row.get("media_pool_item_name")) for row in rows),
    }
    return {
        "count": len(rows),
        "track_usage": {str(key): value for key, value in sorted(usage.items())},
        "rows": rows,
        "checks": checks,
        "ok": all(checks.values()),
    }


def matte_inventory(timeline: Any) -> Dict[str, Any]:
    matches = []
    for track, item in base.all_video_items(timeline):
        summary = base.item_summary(track, item)
        if summary.get("name") == EXPECTED_MATTE["name"]:
            matches.append(summary)
    stable = [
        {key: row.get(key) for key in EXPECTED_MATTE}
        for row in matches
    ]
    return {
        "count": len(matches),
        "rows": matches,
        "ok": len(stable) == 1 and stable[0] == EXPECTED_MATTE,
    }


def partition_inventory(timeline: Any) -> Dict[str, Any]:
    all_rows = stable_timeline_rows(timeline)
    legacy_rows = [
        stable_item_row(track, item)
        for track, item in legacy_basic_title_items(timeline)
    ]
    track_two_rows = [row for row in all_rows if int(row.get("track_index") or 0) == LEGACY_TRACK_INDEX]
    textplus = textplus_inventory(timeline)
    matte = matte_inventory(timeline)
    checks = {
        "legacy_count": len(legacy_rows) == EXPECTED_LEGACY_COUNT,
        "track_two_contains_only_legacy": len(track_two_rows) == EXPECTED_LEGACY_COUNT and sorted(track_two_rows, key=str) == sorted(legacy_rows, key=str),
        "textplus": textplus.get("ok") is True,
        "matte": matte.get("ok") is True,
    }
    return {
        "all_rows": all_rows,
        "legacy_rows": legacy_rows,
        "track_two_rows": track_two_rows,
        "legacy_count": len(legacy_rows),
        "track_two_count": len(track_two_rows),
        "textplus": textplus,
        "matte": matte,
        "checks": checks,
        "ok": all(checks.values()),
    }


def rows_without_legacy(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if not (
            int(row.get("track_index") or 0) == LEGACY_TRACK_INDEX
            and row.get("name") == LEGACY_ITEM_NAME
            and row.get("media_pool_item_name") is None
        )
    ]


def cleanup_target(
    resolve: Any,
    target_name: str,
    original_name: str,
    original_page: str,
    root: Path,
    accepted_hash: str,
) -> Dict[str, Any]:
    return rollout.cleanup_target(resolve, target_name, original_name, original_page, root, accepted_hash)


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
    accepted_hash = str(command.get("accepted_state_sha256") or "")
    cleanup_config = command.get("cleanup")
    if not isinstance(cleanup_config, dict):
        raise ValueError("cleanup_config")
    if cleanup_config.get("source_timeline_name") != SOURCE_TIMELINE_NAME:
        raise ValueError("source_timeline_name")
    if cleanup_config.get("target_timeline_name") != TARGET_TIMELINE_NAME:
        raise ValueError("target_timeline_name")

    report: Dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "backend": "duplicate_v6_plus_delete_legacy_basic_titles",
        "ok": False,
        "started_at": base.utc_now(),
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "final_timeline_name": TARGET_TIMELINE_NAME,
        "failures": [],
        "save_call_count": 0,
        "final_timeline_kept": False,
        "visual_review_required": False,
    }
    original_name = ""
    original_page = str(base.safe_value(resolve, "GetCurrentPage", default="") or "")
    target_created = False

    try:
        source_contract = base.verify_source_contract(root, command)
        report["source_contract_verified_count"] = source_contract["verified_count"]
        base.write_json(report_dir / "source_contract_verification.json", source_contract)

        accepted_path = root / ACCEPTED_STATE_RELATIVE_PATH
        if not accepted_path.is_file() or base.raw_sha256(accepted_path) != accepted_hash:
            raise RuntimeError("accepted_state")

        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        before_timelines = base.project_timeline_snapshot(project)
        original_name = str((before_timelines.get("current") or {}).get("name") or "")
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("v6_source_timeline")
        if base.find_timeline(project, TARGET_TIMELINE_NAME) is not None:
            raise RuntimeError("target_timeline_exists")

        source_unique_id = base.timeline_unique_id(source)
        source_before = partition_inventory(source)
        base.write_json(report_dir / "cleanup_preflight.json", {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "resolve_calls": resolve_calls,
            "original_page": original_page,
            "original_timeline_name": original_name,
            "before_timelines": before_timelines,
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "source_timeline_unique_id": source_unique_id,
            "source_inventory": source_before,
            "accepted_state_sha256": accepted_hash,
            "ok": source_before.get("ok") is True,
        })
        if not source_before.get("ok"):
            raise RuntimeError("v6_source_inventory")

        opened_edit, open_page_call = base.direct_call(resolve, "OpenPage", "edit")
        if not opened_edit:
            raise RuntimeError("open_edit_page")

        duplicate_value, duplicate_call = base.direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
        target = duplicate_value if duplicate_value is not None else base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target is None:
            raise RuntimeError("duplicate_timeline")
        target_created = True
        selected, select_call = base.direct_call(project, "SetCurrentTimeline", target)
        if not selected:
            raise RuntimeError("select_target")

        target_before = partition_inventory(target)
        duplicate_ok = bool(
            target_before.get("ok")
            and target_before.get("all_rows") == source_before.get("all_rows")
        )
        duplicate_setup = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "duplicate_call": duplicate_call,
            "select_call": select_call,
            "open_page_call": open_page_call,
            "target_timeline_name": base.timeline_name(target),
            "target_timeline_unique_id": base.timeline_unique_id(target),
            "source_item_count": len(source_before["all_rows"]),
            "target_item_count": len(target_before["all_rows"]),
            "source_target_stable_inventory_equal": target_before.get("all_rows") == source_before.get("all_rows"),
            "target_inventory": target_before,
            "ok": duplicate_ok,
        }
        base.write_json(report_dir / "duplicate_timeline_setup.json", duplicate_setup)
        if not duplicate_ok:
            raise RuntimeError("duplicate_timeline_setup")

        legacy_items = [item for _, item in legacy_basic_title_items(target)]
        deletion = base.delete_items(target, legacy_items)
        time.sleep(0.30)
        target_after_delete = partition_inventory(target)
        expected_after_rows = rows_without_legacy(source_before["all_rows"])
        actual_after_rows = target_after_delete["all_rows"]
        cleanup_checks = {
            "delete_call": deletion.get("ok") is True,
            "requested_count": deletion.get("requested_count") == EXPECTED_LEGACY_COUNT,
            "legacy_removed": target_after_delete.get("legacy_count") == 0,
            "track_two_empty": target_after_delete.get("track_two_count") == 0,
            "textplus_preserved": target_after_delete.get("textplus", {}).get("ok") is True,
            "matte_preserved": target_after_delete.get("matte", {}).get("ok") is True,
            "nonlegacy_inventory_exact": actual_after_rows == expected_after_rows,
        }
        cleanup_application = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "legacy_track_index": LEGACY_TRACK_INDEX,
            "legacy_item_name": LEGACY_ITEM_NAME,
            "legacy_count_before": len(legacy_items),
            "delete": deletion,
            "legacy_count_after": target_after_delete.get("legacy_count"),
            "track_two_count_after": target_after_delete.get("track_two_count"),
            "textplus_after": target_after_delete.get("textplus"),
            "matte_after": target_after_delete.get("matte"),
            "expected_after_rows": expected_after_rows,
            "actual_after_rows": actual_after_rows,
            "checks": cleanup_checks,
            "ok": all(cleanup_checks.values()),
        }
        base.write_json(report_dir / "legacy_title_cleanup.json", cleanup_application)
        if not cleanup_application["ok"]:
            raise RuntimeError("legacy_title_cleanup")

        save = base.save_project(project_manager)
        report["save_call_count"] += 1 if save.get("success") else 0
        if not save.get("success"):
            raise RuntimeError("save_cleanup")

        project_manager, project, media_pool, reacquire_calls = base.get_project(resolve)
        source_after = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        target_after = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if source_after is None or target_after is None:
            raise RuntimeError("timeline_reacquire")

        source_after_inventory = partition_inventory(source_after)
        target_persistent = partition_inventory(target_after)
        accepted_unchanged = accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash
        source_unchanged = bool(
            base.timeline_unique_id(source_after) == source_unique_id
            and source_after_inventory.get("all_rows") == source_before.get("all_rows")
        )
        persistent_checks = {
            "source_unchanged": source_unchanged,
            "accepted_state_unchanged": accepted_unchanged,
            "legacy_removed": target_persistent.get("legacy_count") == 0,
            "track_two_empty": target_persistent.get("track_two_count") == 0,
            "textplus_preserved": target_persistent.get("textplus", {}).get("ok") is True,
            "matte_preserved": target_persistent.get("matte", {}).get("ok") is True,
            "nonlegacy_inventory_exact": target_persistent.get("all_rows") == expected_after_rows,
        }
        persistent = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "checked_at": base.utc_now(),
            "reacquire_calls": reacquire_calls,
            "source_inventory_before": source_before,
            "source_inventory_after": source_after_inventory,
            "target_inventory": target_persistent,
            "expected_target_rows": expected_after_rows,
            "save": save,
            "checks": persistent_checks,
            "ok": all(persistent_checks.values()),
        }
        base.write_json(report_dir / "persistent_readback.json", persistent)
        if not persistent["ok"]:
            raise RuntimeError("persistent_cleanup_readback")

        report.update({
            "ok": True,
            "finished_at": base.utc_now(),
            "legacy_track_index": LEGACY_TRACK_INDEX,
            "legacy_basic_title_count_before": EXPECTED_LEGACY_COUNT,
            "legacy_basic_title_count_after": 0,
            "track_two_item_count_after": 0,
            "textplus_instance_count": target_persistent["textplus"]["count"],
            "textplus_track_usage": target_persistent["textplus"]["track_usage"],
            "textplus_fusion_comp_count": sum(
                1
                for row in target_persistent["textplus"]["rows"]
                if int(row.get("fusion_comp_count") or 0) == 1
            ),
            "occlusion_matte_preserved": target_persistent["matte"]["ok"],
            "nonlegacy_inventory_unchanged": target_persistent["all_rows"] == expected_after_rows,
            "source_timeline_unchanged": source_unchanged,
            "accepted_state_unchanged": accepted_unchanged,
            "final_timeline_kept": True,
            "final_timeline_unique_id": base.timeline_unique_id(target_after),
            "visual_review_required": True,
            "visual_review_instruction": (
                f"Open {TARGET_TIMELINE_NAME}. Confirm V2 is empty, only the generated Text+ caption instances "
                "on V3-V7 render above the base video, the V4 occlusion matte remains present, and no legacy Basic "
                "Title text overlaps the Text+ captions."
            ),
        })
        base.write_json(report_dir / "cleanup_result.json", report)
        return report

    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc))
        report["traceback"] = traceback.format_exc()
        cleanup = cleanup_target(
            resolve,
            TARGET_TIMELINE_NAME,
            original_name or SOURCE_TIMELINE_NAME,
            original_page,
            root,
            accepted_hash,
        ) if target_created else {
            "attempted": False,
            "probe_deleted": True,
            "accepted_state_unchanged": (
                (root / ACCEPTED_STATE_RELATIVE_PATH).is_file()
                and base.raw_sha256(root / ACCEPTED_STATE_RELATIVE_PATH) == accepted_hash
            ),
            "ok": True,
        }
        if cleanup.get("save_cleanup", {}).get("success"):
            report["save_call_count"] += 1
        report.update({
            "ok": False,
            "finished_at": base.utc_now(),
            "cleanup": cleanup,
            "final_timeline_kept": False,
            "visual_review_required": False,
            "accepted_state_unchanged": cleanup.get("accepted_state_unchanged"),
        })
        base.write_json(report_dir / "cleanup_failure.json", cleanup)
        base.write_json(report_dir / "cleanup_result.json", report)
        return report
