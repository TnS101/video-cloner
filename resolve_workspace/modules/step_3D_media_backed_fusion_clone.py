"""Two-caption live proof using media-backed clips plus imported source Fusion comps.

This is the final bounded test of the media-backed carrier architecture. It reuses
Resolve's already-proven ``MediaPool.AppendToTimeline`` insertion path, assigns
returned items directly instead of inferring them from strict duration matching,
imports the protected COME/they Fusion compositions, saves, reacquires, and keeps
the disposable proof timeline only on PASS. On any failure it deletes the proof
and restores the original timeline/page.
"""
from __future__ import annotations

import importlib.util
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

BASE_PATH = Path(__file__).with_name("step_3D_existing_textplus_clone_probe.py")
_spec = importlib.util.spec_from_file_location("vc_existing_textplus_clone_probe_v1", BASE_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot_load:{BASE_PATH}")
base = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = base
_spec.loader.exec_module(base)

TASK_ID = "DZSQH7AUHJT_STEP_3D_MEDIA_BACKED_FUSION_CLONE_V1"
MODE = "STEP_3D_MEDIA_BACKED_FUSION_CLONE"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3D_media_backed_fusion_clone.py"
SOURCE_TIMELINE_NAME = base.SOURCE_TIMELINE_NAME
EXPECTED_SOURCE_CAPTION_COUNT = base.EXPECTED_SOURCE_CAPTION_COUNT
ACCEPTED_STATE_RELATIVE_PATH = base.ACCEPTED_STATE_RELATIVE_PATH
SOURCE_HASH_ALGORITHM = base.SOURCE_HASH_ALGORITHM
TARGETS = base.TARGETS


def candidate_snapshot(timeline: Any, items: Iterable[Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(items):
        track = base.item_track_index(timeline, item)
        rows.append({
            "index": index,
            "track_index": track,
            "summary": base.item_summary(int(track or 0), item),
            "repr": repr(item),
        })
    return rows


def placement_ok(summary: Dict[str, Any], spec: Dict[str, Any]) -> bool:
    start, end = [int(value) for value in spec["target_range"]]
    return bool(
        int(summary.get("track_index") or 0) == int(spec["target_track"])
        and int(summary.get("start") or -1) == start
        and int(summary.get("end") or -1) in {end, end - 1}
    )


def append_carriers_by_return_order(
    media_pool: Any,
    timeline: Any,
    source: Dict[str, Any],
    specs: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    specs_list = list(specs)
    before_ids = {
        base.item_unique_id(item)
        for _, item in base.all_video_items(timeline)
        if base.item_unique_id(item)
    }
    clip_infos = []
    for spec in specs_list:
        start, end = [int(value) for value in spec["target_range"]]
        duration = end - start
        clip_infos.append({
            "mediaPoolItem": source["media_pool_item"],
            "startFrame": int(source["source_start"]),
            "endFrame": int(source["source_start"]) + duration - 1,
            "mediaType": 1,
            "trackIndex": int(spec["target_track"]),
            "recordFrame": start,
        })

    returned, call = base.direct_call(media_pool, "AppendToTimeline", clip_infos)
    time.sleep(0.30)
    returned_items = list(returned) if isinstance(returned, (list, tuple)) else []
    detected_items = [
        item
        for _, item in base.all_video_items(timeline)
        if base.item_unique_id(item) and base.item_unique_id(item) not in before_ids
    ]

    if len(returned_items) == len(specs_list):
        selected = returned_items
        detection_method = "return_value_order"
    elif len(detected_items) == len(specs_list):
        selected = sorted(
            detected_items,
            key=lambda item: (
                int(base.item_track_index(timeline, item) or 0),
                base.item_start(item),
            ),
        )
        detection_method = "timeline_delta_order"
    else:
        selected = []
        detection_method = "none"

    rows: List[Dict[str, Any]] = []
    assigned: List[Tuple[Dict[str, Any], Any]] = []
    for index, spec in enumerate(specs_list):
        if index >= len(selected):
            rows.append({"cue_id": spec["cue_id"], "assigned": False, "ok": False})
            continue
        raw_item = selected[index]
        name_write = base.set_item_name(raw_item, spec["name"])
        time.sleep(0.10)
        track, reacquired = base.find_named_item(timeline, spec["name"])
        item = reacquired if reacquired is not None else raw_item
        summary = base.item_summary(int(track or base.item_track_index(timeline, item) or 0), item)
        correct_placement = placement_ok(summary, spec)
        row = {
            "cue_id": spec["cue_id"],
            "assigned": True,
            "detection_method": detection_method,
            "name_write": name_write,
            "summary": summary,
            "expected_track": int(spec["target_track"]),
            "expected_range": list(spec["target_range"]),
            "placement_ok": correct_placement,
            "ok": bool(name_write.get("ok") and correct_placement),
        }
        rows.append(row)
        assigned.append((spec, item))

    return {
        "call": call,
        "clip_infos": [
            {key: (str(value) if key == "mediaPoolItem" else value) for key, value in row.items()}
            for row in clip_infos
        ],
        "returned_count": len(returned_items),
        "detected_count": len(detected_items),
        "returned_candidates": candidate_snapshot(timeline, returned_items),
        "detected_candidates": candidate_snapshot(timeline, detected_items),
        "detection_method": detection_method,
        "assigned_count": len(assigned),
        "rows": rows,
        "assigned": assigned,
        "ok": len(assigned) == len(specs_list) and all(row.get("ok") for row in rows),
    }


def import_source_comp(target_item: Any, comp_path: Path) -> Dict[str, Any]:
    before_count = base.as_int(base.safe_value(target_item, "GetFusionCompCount", default=0), 0)
    imported, import_call = base.direct_call(target_item, "ImportFusionComp", str(comp_path))
    comp, poll = base.wait_for_comp(target_item, timeout_seconds=3.0, poll_seconds=0.10)
    if imported is not None:
        comp = imported
    after_count = base.as_int(base.safe_value(target_item, "GetFusionCompCount", default=0), 0)
    names = list(base.safe_value(target_item, "GetFusionCompNameList", default=[]) or [])
    return {
        "strategy": "ImportFusionComp_only",
        "before_count": before_count,
        "after_count": after_count,
        "comp_names": names,
        "import_call": import_call,
        "poll": poll,
        "comp_available": comp is not None or base.get_comp(target_item) is not None,
        "ok": comp is not None or base.get_comp(target_item) is not None,
    }


def cleanup_probe(
    resolve: Any,
    probe_name: str,
    original_name: str,
    original_page: str,
    root: Path,
    accepted_hash: str,
) -> Dict[str, Any]:
    cleanup: Dict[str, Any] = {"attempted": True, "started_at": base.utc_now(), "errors": []}
    try:
        project_manager, project, media_pool, rows = base.get_project(resolve)
        cleanup["resolve_calls"] = rows
        original = base.find_timeline(project, original_name)
        if original is not None:
            value, row = base.direct_call(project, "SetCurrentTimeline", original)
            cleanup["restore_original"] = row
            if not value:
                cleanup["errors"].append("restore_original")
        probe = base.find_timeline(project, probe_name)
        cleanup["probe_found"] = probe is not None
        if probe is not None:
            value, row = base.direct_call(media_pool, "DeleteTimelines", [probe])
            cleanup["delete_probe"] = row
            if not value:
                cleanup["errors"].append("delete_probe")
        cleanup["probe_deleted"] = base.find_timeline(project, probe_name) is None
        save = base.save_project(project_manager)
        cleanup["save_cleanup"] = save
        if not save["success"]:
            cleanup["errors"].append("save_cleanup")
        if original_page:
            value, row = base.direct_call(resolve, "OpenPage", original_page)
            cleanup["restore_page"] = row
            if not value:
                cleanup["errors"].append("restore_page")
    except BaseException as exc:
        cleanup["errors"].append(base.compact_exception(exc))
        cleanup["traceback"] = traceback.format_exc()
    accepted_path = root / ACCEPTED_STATE_RELATIVE_PATH
    cleanup["accepted_state_unchanged"] = accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash
    cleanup["finished_at"] = base.utc_now()
    cleanup["ok"] = bool(
        not cleanup["errors"]
        and cleanup.get("probe_deleted") is True
        and cleanup.get("accepted_state_unchanged") is True
    )
    return cleanup


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
    probe_config = command.get("probe")
    if not isinstance(probe_config, dict):
        raise ValueError("probe")
    probe_name = str(probe_config.get("timeline_name") or "")
    if not probe_name:
        raise ValueError("probe_timeline_name")

    report: Dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "backend": "media_pool_append_plus_import_fusion_comp",
        "ok": False,
        "started_at": base.utc_now(),
        "probe_timeline_name": probe_name,
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "failures": [],
        "save_call_count": 0,
        "probe_timeline_kept": False,
        "visual_review_required": False,
    }
    original_name = ""
    original_page = str(base.safe_value(resolve, "GetCurrentPage", default="") or "")
    duplicate_created = False

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
            raise RuntimeError("source_timeline")
        source_unique_id = base.timeline_unique_id(source)
        source_caption_rows = base.caption_items(source)
        if len(source_caption_rows) != EXPECTED_SOURCE_CAPTION_COUNT:
            raise RuntimeError(f"source_caption_count:{len(source_caption_rows)}")

        source_before = base.source_item_snapshot(source, TARGETS)
        if any(not row.get("found") for row in source_before["rows"]):
            raise RuntimeError("source_target_missing")
        for spec, row in zip(TARGETS, source_before["rows"]):
            summary = row["summary"]
            if [summary["start"], summary["end"]] != spec["source_range"]:
                raise RuntimeError(f"source_range:{spec['cue_id']}")
            if not row["visual"]["text_matched"] or not row["visual"]["center_targets_matched"]:
                raise RuntimeError(f"source_visual:{spec['cue_id']}")

        carrier_source = base.choose_carrier_source(
            source,
            max(spec["target_range"][1] - spec["target_range"][0] for spec in TARGETS),
        )
        if not carrier_source.get("ok"):
            raise RuntimeError("carrier_source")

        opened_edit, open_page_call = base.direct_call(resolve, "OpenPage", "edit")
        if not opened_edit:
            raise RuntimeError("open_edit_page")

        preflight = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "checked_at": base.utc_now(),
            "resolve_calls": resolve_calls,
            "open_page_call": open_page_call,
            "original_page": original_page,
            "before_timelines": before_timelines,
            "original_timeline_name": original_name,
            "source_timeline": {"name": SOURCE_TIMELINE_NAME, "unique_id": source_unique_id},
            "source_caption_count": len(source_caption_rows),
            "source_targets": source_before,
            "carrier_source": {
                key: base.json_safe(value)
                for key, value in carrier_source.items()
                if key not in {"item", "media_pool_item"}
            },
            "targets": TARGETS,
            "accepted_state_sha256": accepted_hash,
        }
        base.write_json(report_dir / "probe_preflight.json", preflight)

        export_dir = report_dir / "source_comp_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        export_rows = []
        source_items: Dict[str, Any] = {}
        for spec in TARGETS:
            track, source_item = base.find_named_item(source, spec["name"])
            if source_item is None:
                raise RuntimeError(f"source_item:{spec['cue_id']}")
            source_items[spec["cue_id"]] = source_item
            comp_path = export_dir / f"{spec['cue_id']}.comp"
            value, row = base.direct_call(source_item, "ExportFusionComp", str(comp_path), 1)
            file_ok = bool(value and comp_path.is_file() and comp_path.stat().st_size > 0)
            export_rows.append({
                "cue_id": spec["cue_id"],
                "name": spec["name"],
                "track": track,
                "call": row,
                "path": str(comp_path),
                "size": comp_path.stat().st_size if comp_path.is_file() else 0,
                "sha256": base.raw_sha256(comp_path) if file_ok else None,
                "ok": file_ok,
            })
            if not file_ok:
                raise RuntimeError(f"source_comp_export:{spec['cue_id']}")
        base.write_json(
            report_dir / "source_comp_exports.json",
            {"rows": export_rows, "exported_count": len(export_rows), "ok": all(row["ok"] for row in export_rows)},
        )

        value, duplicate_call = base.direct_call(source, "DuplicateTimeline", probe_name)
        duplicate = value if value is not None else base.find_timeline(project, probe_name)
        if duplicate is None:
            raise RuntimeError("duplicate_timeline")
        duplicate_created = True
        value, set_current_call = base.direct_call(project, "SetCurrentTimeline", duplicate)
        if not value:
            raise RuntimeError("select_duplicate")

        duplicate_before_captions = base.caption_items(duplicate)
        deletion = base.delete_items(duplicate, [item for _, item in duplicate_before_captions])
        time.sleep(0.20)
        remaining_captions = base.caption_items(duplicate)
        if not deletion.get("ok") or remaining_captions:
            raise RuntimeError(f"caption_cleanup:{len(remaining_captions)}")
        track_setup = base.ensure_video_tracks(duplicate, 5)
        if not track_setup.get("ok"):
            raise RuntimeError("video_tracks")

        duplicate_evidence = {
            "duplicate_call": duplicate_call,
            "set_current_call": set_current_call,
            "duplicate_name": base.timeline_name(duplicate),
            "duplicate_unique_id": base.timeline_unique_id(duplicate),
            "caption_count_before_delete": len(duplicate_before_captions),
            "caption_delete": deletion,
            "caption_count_after_delete": len(remaining_captions),
            "track_setup": track_setup,
        }
        base.write_json(report_dir / "duplicate_timeline_setup.json", duplicate_evidence)

        append = append_carriers_by_return_order(media_pool, duplicate, carrier_source, TARGETS)
        base.write_json(
            report_dir / "carrier_append.json",
            base.json_safe({key: value for key, value in append.items() if key != "assigned"}),
        )
        report["append_returned_count"] = append["returned_count"]
        report["append_detected_count"] = append["detected_count"]
        report["carrier_append_count"] = append["assigned_count"]
        if not append.get("ok"):
            raise RuntimeError("carrier_append_placement")

        clone_rows = []
        for spec, target_item in append["assigned"]:
            export_path = export_dir / f"{spec['cue_id']}.comp"
            clone = import_source_comp(target_item, export_path)
            visual = base.visual_readback(target_item, spec)
            row = {
                "cue_id": spec["cue_id"],
                "name": spec["name"],
                "target_summary": base.item_summary(int(spec["target_track"]), target_item),
                "clone": clone,
                "visual": visual,
                "ok": bool(clone.get("ok") and visual.get("text_matched") and visual.get("center_targets_matched")),
            }
            clone_rows.append(row)
            base.write_json(
                report_dir / "comp_clone_progress.json",
                {"completed_count": sum(1 for item in clone_rows if item["ok"]), "rows": clone_rows},
            )
            if not row["ok"]:
                raise RuntimeError(f"media_fusion_import:{spec['cue_id']}")
        base.write_json(
            report_dir / "comp_clone_application.json",
            {"rows": clone_rows, "completed_count": len(clone_rows), "ok": True},
        )

        first_save = base.save_project(project_manager)
        report["save_call_count"] += 1 if first_save.get("success") else 0
        if not first_save.get("success"):
            raise RuntimeError("save_probe")

        project_manager, project, media_pool, reacquire_calls = base.get_project(resolve)
        duplicate_after = base.find_timeline(project, probe_name)
        source_after = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if duplicate_after is None or source_after is None:
            raise RuntimeError("persistent_timeline_reacquire")

        target_rows = []
        for spec in TARGETS:
            track, item = base.find_named_item(duplicate_after, spec["name"])
            if item is None:
                target_rows.append({"cue_id": spec["cue_id"], "found": False, "ok": False})
                continue
            summary = base.item_summary(int(track or 0), item)
            visual = base.visual_readback(item, spec)
            timing_ok = placement_ok(summary, spec)
            target_rows.append({
                "cue_id": spec["cue_id"],
                "found": True,
                "summary": summary,
                "visual": visual,
                "timing_ok": timing_ok,
                "ok": bool(timing_ok and visual["text_matched"] and visual["center_targets_matched"] and visual["comp_available"]),
            })

        source_after_snapshot = base.source_item_snapshot(source_after, TARGETS)
        source_protected = bool(
            base.timeline_unique_id(source_after) == source_unique_id
            and base.source_unchanged(source_before, source_after_snapshot)
        )
        accepted_unchanged = accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash
        targets_ok = len(target_rows) == len(TARGETS) and all(row.get("ok") for row in target_rows)
        persistent = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "checked_at": base.utc_now(),
            "reacquire_calls": reacquire_calls,
            "targets": target_rows,
            "targets_ok": targets_ok,
            "source_before": source_before,
            "source_after": source_after_snapshot,
            "source_timeline_unchanged": source_protected,
            "accepted_state_unchanged": accepted_unchanged,
            "probe_timeline_kept": True,
            "save": first_save,
        }
        base.write_json(report_dir / "persistent_readback.json", persistent)
        if not targets_ok:
            raise RuntimeError("persistent_target_readback")
        if not source_protected:
            raise RuntimeError("source_timeline_changed")
        if not accepted_unchanged:
            raise RuntimeError("accepted_state_changed")

        if original_page:
            opened, restore_page_call = base.direct_call(resolve, "OpenPage", original_page)
            report["restore_page_call"] = restore_page_call
            if not opened:
                raise RuntimeError("restore_page")

        report.update({
            "ok": True,
            "finished_at": base.utc_now(),
            "source_comp_export_count": len(export_rows),
            "comp_clone_count": len(clone_rows),
            "target_readback_count": sum(1 for row in target_rows if row.get("ok")),
            "source_timeline_unchanged": source_protected,
            "accepted_state_unchanged": accepted_unchanged,
            "probe_timeline_kept": True,
            "probe_timeline_unique_id": base.timeline_unique_id(duplicate_after),
            "visual_review_required": True,
            "visual_review_window": [430, 452],
            "visual_review_instruction": (
                f"Open {probe_name} and review frames 430-452. COME must retain its slide/persistence; "
                "lower-case they must remain independently positioned and must not collide with COME."
            ),
        })
        base.write_json(report_dir / "probe_result.json", report)
        return report

    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc))
        report["traceback"] = traceback.format_exc()
        cleanup = cleanup_probe(
            resolve,
            probe_name,
            original_name or SOURCE_TIMELINE_NAME,
            original_page,
            root,
            accepted_hash,
        ) if duplicate_created else {
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
            "probe_timeline_kept": False,
            "visual_review_required": False,
            "accepted_state_unchanged": cleanup.get("accepted_state_unchanged"),
        })
        base.write_json(report_dir / "probe_cleanup.json", cleanup)
        base.write_json(report_dir / "probe_result.json", report)
        return report
