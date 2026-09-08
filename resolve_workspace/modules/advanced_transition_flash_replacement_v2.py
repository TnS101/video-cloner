"""Replace stale flash-cut substitutes with source-backed flash transitions.

Architecture family: advanced_transition_flash_replacement_v2.
Architecture attempt: 2 (first visual correction after V1 technical PASS).

The accepted source timeline is duplicated to a new isolated target. Exactly five
FCPXML-imported ``Cross Dissolve`` items that overlap the source-backed flash-cut
boundaries are removed from the duplicate, then the technically proven V1/R5
four-frame Fusion flash carriers are applied unchanged. The source timeline,
media-backed clip geometry, captions, occlusion, and every unrelated transition
remain protected.
"""
from __future__ import annotations

import importlib.util
import traceback
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

_PARENT_PATH = Path(__file__).with_name("advanced_transition_flash_application_v1.py")
_PARENT_SPEC = importlib.util.spec_from_file_location("vc_flash_v1_r5_parent", _PARENT_PATH)
if _PARENT_SPEC is None or _PARENT_SPEC.loader is None:
    raise ImportError(f"cannot_load_parent:{_PARENT_PATH}")
V1 = importlib.util.module_from_spec(_PARENT_SPEC)
_PARENT_SPEC.loader.exec_module(V1)

TASK_ID = "DZSQH7AUHJT_ADVANCED_TRANSITION_FLASH_REPLACEMENT_V2"
MODE = "ADVANCED_TRANSITION_FLASH_REPLACEMENT_V2"
VERSION = "advanced_transition_flash_replacement_v2_0"
ARCHITECTURE_FAMILY = "advanced_transition_flash_replacement_v2"
ATTEMPT_NUMBER = 2

SOURCE_TIMELINE_NAME = V1.SOURCE_TIMELINE_NAME
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_flash_transition_v2"
EXPECTED_TEXTPLUS_COUNT = V1.EXPECTED_TEXTPLUS_COUNT
EXPECTED_FLASH_FRAMES = V1.EXPECTED_FLASH_FRAMES
FLASH_PREFIX = V1.FLASH_PREFIX

EXPECTED_STALE_NATIVE_TRANSITIONS = {
    96: ("Cross Dissolve", 92, 100),
    377: ("Cross Dissolve", 373, 382),
    426: ("Cross Dissolve", 422, 431),
    454: ("Cross Dissolve", 449, 459),
    758: ("Cross Dissolve", 754, 762),
}

NATIVE_TRANSITION_NAME_HINTS = (
    "cross dissolve",
    "dissolve",
    "slide",
    "wipe",
    "fade",
    "transition",
    "push",
    "blur",
    "iris",
    "dip to",
)


def validate_plan(plan: Mapping[str, Any]) -> None:
    if plan.get("schema") != "video_cloner_flash_transition_replacement_plan" or plan.get("schema_version") != 2:
        raise ValueError("plan_schema")
    if plan.get("task_id") != TASK_ID:
        raise ValueError("plan_task_id")
    if plan.get("architecture_family") != ARCHITECTURE_FAMILY or int(plan.get("attempt_number") or 0) != ATTEMPT_NUMBER:
        raise ValueError("plan_architecture")
    if plan.get("source_timeline_name") != SOURCE_TIMELINE_NAME:
        raise ValueError("plan_source_timeline")
    if plan.get("target_timeline_name") != TARGET_TIMELINE_NAME:
        raise ValueError("plan_target_timeline")
    if int(plan.get("expected_textplus_count") or 0) != EXPECTED_TEXTPLUS_COUNT:
        raise ValueError("plan_textplus_count")

    rows = plan.get("flashes")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED_FLASH_FRAMES):
        raise ValueError("plan_flash_count")
    actual_frames = tuple(int(row.get("cut_frame") or -1) for row in rows if isinstance(row, Mapping))
    if actual_frames != EXPECTED_FLASH_FRAMES:
        raise ValueError(f"plan_flash_frames:{actual_frames}")

    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise ValueError(f"plan_flash_row:{index}")
        cut = EXPECTED_FLASH_FRAMES[index - 1]
        expected_name = f"{FLASH_PREFIX}{index:03d}_frame_{cut:04d}"
        stale = row.get("stale_native_transition")
        if not isinstance(stale, Mapping):
            raise ValueError(f"plan_stale_transition:{index}")
        expected_stale = EXPECTED_STALE_NATIVE_TRANSITIONS[cut]
        checks = (
            row.get("transition_type") == "flash_cut",
            row.get("confidence") == "high",
            row.get("editor_actionable") is True,
            int(row.get("duration_frames") or 0) == 4,
            int(row.get("outgoing_frames") or 0) == 2,
            int(row.get("incoming_frames") or 0) == 2,
            int(row.get("start_frame") or -1) == cut - 2,
            row.get("name") == expected_name,
            row.get("flash_color") == [1.0, 1.0, 1.0],
            row.get("alpha_keyframes") == [[0, 0.0], [2, 0.75], [3, 0.0]],
            stale.get("name") == expected_stale[0],
            int(stale.get("start_frame") or -1) == expected_stale[1],
            int(stale.get("end_frame") or -1) == expected_stale[2],
            int(stale.get("duration_frames") or -1) == expected_stale[2] - expected_stale[1],
        )
        if not all(checks):
            raise ValueError(f"plan_flash_contract:{index}")

    plan_for_hash = dict(plan)
    expected_hash = str(plan_for_hash.pop("plan_sha256", "") or "")
    if not expected_hash or V1.canonical_sha256(plan_for_hash) != expected_hash:
        raise ValueError("plan_hash")


def item_has_media_pool_item(item: Any) -> bool:
    return V1.safe_call(item, "GetMediaPoolItem", default=None) is not None


def is_native_transition_item(item: Any) -> bool:
    if item_has_media_pool_item(item):
        return False
    name = V1.item_name(item).lower().strip()
    return bool(name and any(hint in name for hint in NATIVE_TRANSITION_NAME_HINTS))


def native_transition_snapshot(timeline: Any) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for track_index, item in V1.all_video_items(timeline):
        if not is_native_transition_item(item):
            continue
        rows.append({
            "name": V1.item_name(item),
            "track_index": track_index,
            "start": V1.item_start(item),
            "end": V1.item_end(item),
            "duration": V1.item_duration(item),
        })
    rows.sort(key=lambda row: (row["track_index"], row["start"], row["end"], row["name"]))
    return {"count": len(rows), "rows": rows, "sha256": V1.canonical_sha256(rows)}


def media_geometry_snapshot(timeline: Any) -> Dict[str, Any]:
    """Snapshot all pre-existing media-backed geometry, excluding V2 flash carriers."""
    rows: List[Dict[str, Any]] = []
    for track_index, item in V1.all_video_items(timeline):
        name = V1.item_name(item)
        if name.startswith(FLASH_PREFIX):
            continue
        media_pool_item = V1.safe_call(item, "GetMediaPoolItem", default=None)
        if media_pool_item is None:
            continue
        rows.append({
            "name": name,
            "media_pool_item_name": str(V1.safe_call(media_pool_item, "GetName", default="") or ""),
            "track_index": track_index,
            "start": V1.item_start(item),
            "end": V1.item_end(item),
            "duration": V1.item_duration(item),
        })
    rows.sort(key=lambda row: (row["track_index"], row["start"], row["end"], row["name"], row["media_pool_item_name"]))
    return {"count": len(rows), "rows": rows, "sha256": V1.canonical_sha256(rows)}


def stale_specs(flashes: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    for row in flashes:
        stale = row.get("stale_native_transition") if isinstance(row, Mapping) else None
        if not isinstance(stale, Mapping):
            raise ValueError("stale_transition_spec")
        result.append({
            "cut_frame": int(row["cut_frame"]),
            "name": str(stale["name"]),
            "start": int(stale["start_frame"]),
            "end": int(stale["end_frame"]),
            "duration": int(stale["duration_frames"]),
        })
    return result


def transition_key(row: Mapping[str, Any]) -> Tuple[str, int, int]:
    return (str(row.get("name") or ""), int(row.get("start") or 0), int(row.get("end") or 0))


def stale_transition_snapshot(timeline: Any, flashes: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    expected = {transition_key(row) for row in stale_specs(flashes)}
    rows = [row for row in native_transition_snapshot(timeline)["rows"] if transition_key(row) in expected]
    rows.sort(key=lambda row: (row["start"], row["end"], row["name"], row["track_index"]))
    return {"count": len(rows), "rows": rows, "sha256": V1.canonical_sha256(rows)}


def expected_native_rows_after_removal(
    source_native: Mapping[str, Any],
    flashes: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    targeted = {transition_key(row) for row in stale_specs(flashes)}
    rows = [dict(row) for row in list(source_native.get("rows") or []) if transition_key(row) not in targeted]
    rows.sort(key=lambda row: (row["track_index"], row["start"], row["end"], row["name"]))
    return rows


def remove_stale_native_transitions(timeline: Any, flashes: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    before_native = native_transition_snapshot(timeline)
    before_media = media_geometry_snapshot(timeline)
    specs = stale_specs(flashes)
    matches: List[Tuple[Dict[str, Any], Any, int]] = []
    match_rows: List[Dict[str, Any]] = []
    errors: List[str] = []

    for spec in specs:
        candidates: List[Tuple[int, Any]] = []
        for track_index, item in V1.all_video_items(timeline):
            if (
                is_native_transition_item(item)
                and V1.item_name(item) == spec["name"]
                and V1.item_start(item) == spec["start"]
                and V1.item_end(item) == spec["end"]
                and V1.item_duration(item) == spec["duration"]
            ):
                candidates.append((track_index, item))
        match_rows.append({
            "cut_frame": spec["cut_frame"],
            "name": spec["name"],
            "start": spec["start"],
            "end": spec["end"],
            "duration": spec["duration"],
            "match_count": len(candidates),
            "track_indices": [track for track, _ in candidates],
        })
        if len(candidates) != 1:
            errors.append(f"stale_transition_match:{spec['cut_frame']}:{len(candidates)}")
        else:
            matches.append((spec, candidates[0][1], candidates[0][0]))

    if errors:
        return {
            "ok": False,
            "delete_count": 0,
            "errors": errors,
            "matches": match_rows,
            "before_native": before_native,
            "before_media": before_media,
        }

    items = [item for _, item, _ in matches]
    value, delete_call = V1.direct_call(timeline, "DeleteClips", items, False)
    after_native = native_transition_snapshot(timeline)
    after_media = media_geometry_snapshot(timeline)
    stale_after = stale_transition_snapshot(timeline, flashes)
    expected_unrelated = expected_native_rows_after_removal(before_native, flashes)
    unrelated_unchanged = after_native["sha256"] == V1.canonical_sha256(expected_unrelated)
    media_unchanged = after_media["sha256"] == before_media["sha256"]
    ok = bool(
        value
        and stale_after["count"] == 0
        and unrelated_unchanged
        and media_unchanged
    )
    if not value:
        errors.append("delete_call")
    if stale_after["count"] != 0:
        errors.append(f"stale_remaining:{stale_after['count']}")
    if not unrelated_unchanged:
        errors.append("unrelated_transition_changed")
    if not media_unchanged:
        errors.append("media_geometry_changed")
    return {
        "ok": ok,
        "delete_count": len(items) if ok else 0,
        "errors": errors,
        "matches": match_rows,
        "delete_call": delete_call,
        "before_native": before_native,
        "after_native": after_native,
        "stale_after": stale_after,
        "before_media": before_media,
        "after_media": after_media,
        "unrelated_transitions_unchanged": unrelated_unchanged,
        "media_geometry_unchanged": media_unchanged,
    }


def source_state(timeline: Any) -> Dict[str, Any]:
    return {
        "captions": V1.caption_snapshot(timeline),
        "native_transitions": native_transition_snapshot(timeline),
        "media_geometry": media_geometry_snapshot(timeline),
    }


def source_state_unchanged(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    return bool(
        before["captions"]["sha256"] == after["captions"]["sha256"]
        and before["native_transitions"]["sha256"] == after["native_transitions"]["sha256"]
        and before["media_geometry"]["sha256"] == after["media_geometry"]["sha256"]
    )


def target_contract(
    source: Mapping[str, Any],
    target: Any,
    flashes: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    target_captions = V1.caption_snapshot(target)
    target_native = native_transition_snapshot(target)
    target_media = media_geometry_snapshot(target)
    stale = stale_transition_snapshot(target, flashes)
    expected_track = int(source["captions"]["video_track_count"]) + 1
    flash = V1.flash_snapshot(target, flashes, expected_track)
    expected_native_rows = expected_native_rows_after_removal(source["native_transitions"], flashes)
    expected_native_hash = V1.canonical_sha256(expected_native_rows)
    result = {
        "caption_snapshot": target_captions,
        "native_transition_snapshot": target_native,
        "media_geometry_snapshot": target_media,
        "stale_transition_snapshot": stale,
        "flash_snapshot": flash,
        "caption_count_ok": target_captions["count"] == EXPECTED_TEXTPLUS_COUNT,
        "caption_geometry_unchanged": target_captions["sha256"] == source["captions"]["sha256"],
        "media_geometry_unchanged": target_media["sha256"] == source["media_geometry"]["sha256"],
        "unrelated_transitions_unchanged": target_native["sha256"] == expected_native_hash,
        "stale_transitions_absent": stale["count"] == 0,
        "track_count_ok": target_captions["video_track_count"] == expected_track,
    }
    result["ok"] = bool(
        result["caption_count_ok"]
        and result["caption_geometry_unchanged"]
        and result["media_geometry_unchanged"]
        and result["unrelated_transitions_unchanged"]
        and result["stale_transitions_absent"]
        and result["track_count_ok"]
        and flash["ok"]
    )
    return result


def run(resolve: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    root = V1.repository_root()
    command = context.get("command") if isinstance(context, Mapping) else None
    if not isinstance(command, Mapping):
        raise ValueError("command")
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    if command.get("task_id") != TASK_ID or command.get("mode") != MODE or not run_id:
        raise ValueError("command_identity")
    flash_config = command.get("flash")
    if not isinstance(flash_config, Mapping):
        raise ValueError("flash_config")
    run_mode = str(flash_config.get("run_mode") or "")
    if run_mode not in {"apply", "idempotency"}:
        raise ValueError("run_mode")

    report_dir = V1.relative_path(root, command.get("artifacts_dir"))
    report_dir.mkdir(parents=True, exist_ok=True)
    plan_path = V1.relative_path(root, flash_config.get("plan_path"))
    plan = V1.load_json(plan_path)
    validate_plan(plan)
    flashes = list(plan["flashes"])

    report: Dict[str, Any] = {
        "schema_version": 2,
        "task_id": TASK_ID,
        "version": VERSION,
        "architecture_family": ARCHITECTURE_FAMILY,
        "attempt_number": ATTEMPT_NUMBER,
        "run_id": run_id,
        "run_mode": run_mode,
        "ok": False,
        "started_at": V1.utc_now(),
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "expected_textplus_count": EXPECTED_TEXTPLUS_COUNT,
        "expected_flash_count": len(flashes),
        "expected_stale_transition_delete_count": len(flashes),
        "save_call_count": 0,
        "timeline_duplicate_count": 0,
        "stale_transition_delete_count": 0,
        "video_track_add_count": 0,
        "flash_carrier_append_count": 0,
        "fusion_flash_configure_count": 0,
        "source_timeline_unchanged": False,
        "visual_approval_required": run_mode == "apply",
        "failures": [],
    }
    duplicate_created = False
    saved = False
    project_manager = project = media_pool = source = None
    try:
        report["source_contract"] = V1.verify_source_contract(root, command)

        project_manager = V1.safe_call(resolve, "GetProjectManager", default=None)
        if project_manager is None:
            raise RuntimeError("project_manager")
        project = V1.safe_call(project_manager, "GetCurrentProject", default=None)
        if project is None:
            raise RuntimeError("project")
        media_pool = V1.safe_call(project, "GetMediaPool", default=None)
        if media_pool is None:
            raise RuntimeError("media_pool")

        source = V1.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        source_before = source_state(source)
        report["source_before"] = source_before["captions"]
        report["source_transition_before"] = source_before["native_transitions"]
        report["source_media_before"] = source_before["media_geometry"]
        if source_before["captions"]["count"] != EXPECTED_TEXTPLUS_COUNT:
            raise RuntimeError(f"source_textplus_count:{source_before['captions']['count']}")
        source_stale = stale_transition_snapshot(source, flashes)
        report["source_stale_transition_snapshot"] = source_stale
        if source_stale["count"] != len(flashes):
            raise RuntimeError(f"source_stale_transition_count:{source_stale['count']}")

        existing_target = V1.find_timeline(project, TARGET_TIMELINE_NAME)
        if run_mode == "idempotency":
            if existing_target is None:
                raise RuntimeError("idempotency_target_missing")
            target_before = target_contract(source_before, existing_target, flashes)
            report["target_before"] = target_before
            if not target_before["ok"]:
                raise RuntimeError("idempotency_target_contract")
            source_after = source_state(source)
            report["source_after"] = source_after["captions"]
            report["source_transition_after"] = source_after["native_transitions"]
            report["source_media_after"] = source_after["media_geometry"]
            report["source_timeline_unchanged"] = source_state_unchanged(source_before, source_after)
            report["target_after"] = target_contract(source_after, existing_target, flashes)
            report["idempotent"] = bool(
                report["source_timeline_unchanged"]
                and report["target_after"]["ok"]
                and report["save_call_count"] == 0
                and report["timeline_duplicate_count"] == 0
                and report["stale_transition_delete_count"] == 0
                and report["video_track_add_count"] == 0
                and report["flash_carrier_append_count"] == 0
                and report["fusion_flash_configure_count"] == 0
            )
            report["ok"] = report["idempotent"]
            if not report["ok"]:
                raise RuntimeError("idempotency_contract")
            report["finished_at"] = V1.utc_now()
            V1.write_json(report_dir / "flash_transition_replacement.json", report)
            return report

        if existing_target is not None:
            raise RuntimeError("target_exists")

        value, duplicate_call = V1.direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
        target = value if value is not None else V1.find_timeline(project, TARGET_TIMELINE_NAME)
        report["duplicate_call"] = duplicate_call
        if target is None:
            raise RuntimeError("duplicate_timeline")
        duplicate_created = True
        report["timeline_duplicate_count"] = 1
        if V1.timeline_name(target) != TARGET_TIMELINE_NAME:
            raise RuntimeError("target_timeline_name")

        value, set_current = V1.direct_call(project, "SetCurrentTimeline", target)
        report["set_current_target"] = set_current
        if not value:
            raise RuntimeError("set_current_target")

        duplicated_state = source_state(target)
        report["duplicate_caption_snapshot"] = duplicated_state["captions"]
        report["duplicate_transition_snapshot"] = duplicated_state["native_transitions"]
        report["duplicate_media_snapshot"] = duplicated_state["media_geometry"]
        if (
            duplicated_state["captions"]["count"] != EXPECTED_TEXTPLUS_COUNT
            or duplicated_state["captions"]["sha256"] != source_before["captions"]["sha256"]
            or duplicated_state["native_transitions"]["sha256"] != source_before["native_transitions"]["sha256"]
            or duplicated_state["media_geometry"]["sha256"] != source_before["media_geometry"]["sha256"]
        ):
            raise RuntimeError("duplicate_source_state")

        removal = remove_stale_native_transitions(target, flashes)
        report["stale_transition_removal"] = V1.json_safe(removal)
        if not removal["ok"]:
            raise RuntimeError("stale_flash_transition_removal")
        report["stale_transition_delete_count"] = int(removal["delete_count"])

        post_removal_captions = V1.caption_snapshot(target)
        report["post_removal_caption_snapshot"] = post_removal_captions
        if post_removal_captions["sha256"] != source_before["captions"]["sha256"]:
            raise RuntimeError("caption_changed_by_transition_removal")

        track_setup = V1.ensure_extra_video_track(target, int(source_before["captions"]["video_track_count"]))
        report["track_setup"] = track_setup
        if not track_setup["ok"]:
            raise RuntimeError("flash_track")
        report["video_track_add_count"] = 1
        flash_track = int(track_setup["target_track"])

        carrier = V1.choose_carrier_source(target, 4)
        report["carrier_source"] = {k: V1.json_safe(v) for k, v in carrier.items() if k not in {"item", "media_pool_item"}}
        if not carrier["ok"]:
            raise RuntimeError("carrier_source")

        append = V1.append_flash_carriers(media_pool, target, carrier, flashes, flash_track)
        report["append"] = {k: V1.json_safe(v) for k, v in append.items() if k != "assigned"}
        if not append["ok"]:
            raise RuntimeError("flash_append")
        report["flash_carrier_append_count"] = len(flashes)

        configure_rows = []
        for index, (spec, item) in enumerate(append["assigned"], start=1):
            row = V1.configure_flash(item, spec, index)
            configure_rows.append(row)
            if not row.get("ok"):
                report["configure_rows"] = configure_rows
                raise RuntimeError(f"flash_fusion:{index}")
        report["configure_rows"] = configure_rows
        report["fusion_flash_configure_count"] = len(configure_rows)

        target_before_save = target_contract(source_before, target, flashes)
        report["target_before_save"] = target_before_save
        if not target_before_save["ok"]:
            raise RuntimeError("pre_save_target_contract")
        source_mid = source_state(source)
        report["source_mid"] = source_mid["captions"]
        report["source_transition_mid"] = source_mid["native_transitions"]
        report["source_media_mid"] = source_mid["media_geometry"]
        if not source_state_unchanged(source_before, source_mid):
            raise RuntimeError("source_changed_before_save")

        value, save_call = V1.direct_call(project_manager, "SaveProject")
        report["save_call"] = save_call
        report["save_call_count"] = 1
        if not value:
            raise RuntimeError("save_project")
        saved = True

        persistent_target = V1.find_timeline(project, TARGET_TIMELINE_NAME)
        if persistent_target is None:
            raise RuntimeError("persistent_target_missing")
        source_after = source_state(source)
        target_after = target_contract(source_after, persistent_target, flashes)
        report["source_after"] = source_after["captions"]
        report["source_transition_after"] = source_after["native_transitions"]
        report["source_media_after"] = source_after["media_geometry"]
        report["target_after"] = target_after
        report["source_timeline_unchanged"] = source_state_unchanged(source_before, source_after)
        report["persistent_readback_ok"] = bool(report["source_timeline_unchanged"] and target_after["ok"])
        report["ok"] = report["persistent_readback_ok"]
        if not report["ok"]:
            raise RuntimeError("persistent_readback")

        report["finished_at"] = V1.utc_now()
        V1.write_json(report_dir / "flash_transition_replacement.json", report)
        return report

    except BaseException as exc:
        report["failures"].append(f"{type(exc).__name__}: {exc}")
        report["traceback"] = traceback.format_exc()
        if duplicate_created and not saved and project_manager is not None and project is not None and media_pool is not None and source is not None:
            report["cleanup"] = V1.cleanup_failed_duplicate(project_manager, project, media_pool, source, TARGET_TIMELINE_NAME)
            report["save_call_count"] += 1
        report["finished_at"] = V1.utc_now()
        try:
            V1.write_json(report_dir / "flash_transition_replacement.json", report)
        except Exception:
            pass
        return report
