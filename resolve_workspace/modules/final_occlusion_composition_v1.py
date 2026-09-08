"""Finalize the approved five-frame caption foreground occlusion composition.

This task is intentionally narrow:
- source is the visually accepted 114-Text+ post-metrics timeline;
- duplicate source into one isolated target;
- move the already-existing approved RGBA matte above every caption track;
- mutate no caption item or Text+ input;
- prove caption state equality before save and after persistent readback;
- prove the second occlusion application is a no-op (idempotency).

No caption detection, recreation, geometry/style repair, animation rewrite, or
baked-caption removal is performed here.
"""
from __future__ import annotations

import importlib.util
import hashlib
import json
import math
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

TASK_ID = "DZSQH7AUHJT_FINAL_OCCLUSION_COMPOSITION_V1"
MODE = "FINAL_OCCLUSION_COMPOSITION"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/final_occlusion_composition_v1.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_occlusion_complete_v1"
EXPECTED_TEXTPLUS_COUNT = 114
MATTE_NAME = "VC_OCCLUSION_RGBA_matte_span_0001_sub_0052"
MATTE_RANGE = (429, 434)
MATTE_DURATION = 5
CAPTION_PREFIXES = ("VC_TEXTPLUS_", "VC_VISUAL_FIRST_FULL_")
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"

POST_MODULE_PATH = Path(__file__).with_name("step_3E_post_visual_metrics_polish_v1.py")
_spec = importlib.util.spec_from_file_location("vc_post_metrics_for_final_occlusion", POST_MODULE_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot_load:{POST_MODULE_PATH}")
post = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = post
_spec.loader.exec_module(post)

previous = post.load_previous()
old = previous.load_old()
full, pilot, v6, base, media, visual = old.load_runtime()

# Properties explicitly frozen by the project monotonic non-regression rule.
# Dense per-frame values plus raw keyframe topology are captured for each.
CAPTION_PROPERTIES = (
    "StyledText",
    "Center",
    "Size",
    "Font",
    "Style",
    "Red1",
    "Green1",
    "Blue1",
    "Alpha1",
    "Opacity1",
    "Enabled2",
    "Red2",
    "Green2",
    "Blue2",
    "Alpha2",
    "Thickness2",
    "Opacity2",
    "Enabled3",
    "Red3",
    "Green3",
    "Blue3",
    "Alpha3",
    "Thickness3",
    "Opacity3",
)

STABLE_INVENTORY_FIELDS = (
    "name",
    "track_index",
    "start",
    "end",
    "duration",
    "fusion_comp_count",
    "media_pool_item_name",
)


def _normalized(value: Any) -> Any:
    """Stable JSON-like normalization suitable for cross-duplicate comparison."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return round(value, 9)
    if isinstance(value, Mapping):
        return {str(key): _normalized(val) for key, val in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalized(val) for val in value]
    safe = base.json_safe(value)
    if safe is value:
        return {"python_type": type(value).__name__}
    return _normalized(safe)


def _input_object(tool: Any, name: str) -> Any:
    return base.find_input(tool, name)


def _keyframe_structure(input_object: Any) -> Dict[str, Any]:
    if input_object is None:
        return {}
    output = base.safe_value(input_object, "GetConnectedOutput", default=None)
    keyframes = base.safe_value(input_object, "GetKeyFrames", default=None)
    if keyframes is None and output is not None:
        keyframes = base.safe_value(output, "GetKeyFrames", default=None)
    return _normalized(keyframes or {})


def _input_topology(input_object: Any) -> Dict[str, Any]:
    if input_object is None:
        return {"exists": False, "connected": False, "keyframes": {}}
    attrs = base.safe_value(input_object, "GetAttrs", default={}) or {}
    output = base.safe_value(input_object, "GetConnectedOutput", default=None)
    return {
        "exists": True,
        "connected": output is not None,
        "data_type": attrs.get("INPS_DataType"),
        "keyframes": _keyframe_structure(input_object),
    }


def caption_items(timeline: Any) -> list[tuple[int, Any]]:
    rows: list[tuple[int, Any]] = []
    for track, item in base.all_video_items(timeline):
        if base.item_name(item).startswith(CAPTION_PREFIXES):
            rows.append((int(track), item))
    return sorted(rows, key=lambda pair: (pair[0], base.item_start(pair[1]), base.item_name(pair[1])))


def caption_track_max(timeline: Any) -> int:
    tracks = [track for track, _ in caption_items(timeline)]
    if not tracks:
        raise RuntimeError("caption_tracks_missing")
    return max(tracks)


def _property_snapshot(tool: Any, name: str, duration: int) -> Dict[str, Any]:
    input_object = _input_object(tool, name)
    topology = _input_topology(input_object)
    if not topology["exists"]:
        return topology
    values = [
        _normalized(base.read_input(tool, name, local_frame))
        for local_frame in range(max(1, int(duration)))
    ]
    topology["values"] = values
    return topology


def caption_snapshot(timeline: Any) -> Dict[str, Any]:
    rows = []
    for track, item in caption_items(timeline):
        summary = base.item_summary(track, item)
        comp = base.get_comp(item)
        tool = base.get_text_tool(comp)
        if comp is None or tool is None:
            raise RuntimeError(f"caption_text_tool:{base.item_name(item)}")
        duration = int(summary.get("duration") or 0)
        if duration <= 0:
            raise RuntimeError(f"caption_duration:{base.item_name(item)}")
        rows.append(
            {
                "name": base.item_name(item),
                "summary": {field: summary.get(field) for field in STABLE_INVENTORY_FIELDS},
                "clip_enabled": _normalized(base.safe_value(item, "GetClipEnabled", default=None)),
                "properties": {
                    name: _property_snapshot(tool, name, duration)
                    for name in CAPTION_PROPERTIES
                },
            }
        )
    names = [row["name"] for row in rows]
    if len(rows) != EXPECTED_TEXTPLUS_COUNT:
        raise RuntimeError(f"caption_count:{len(rows)}")
    if len(set(names)) != EXPECTED_TEXTPLUS_COUNT:
        raise RuntimeError("caption_name_duplicate")
    return {
        "count": len(rows),
        "names": names,
        "rows": rows,
        "sha256": hashlib.sha256(
            json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
    }


def caption_snapshots_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return left.get("count") == right.get("count") and left.get("sha256") == right.get("sha256") and left.get("rows") == right.get("rows")


def stable_inventory(timeline: Any, *, exclude_matte: bool = False) -> list[tuple[Any, ...]]:
    rows = []
    for track, item in base.all_video_items(timeline):
        summary = base.item_summary(int(track), item)
        if exclude_matte and summary.get("name") == MATTE_NAME:
            continue
        rows.append(tuple(summary.get(field) for field in STABLE_INVENTORY_FIELDS))
    return sorted(rows, key=lambda row: tuple("" if value is None else str(value) for value in row))


def occlusion_inventory(timeline: Any) -> list[Dict[str, Any]]:
    rows = [
        base.item_summary(int(track), item)
        for track, item in base.all_video_items(timeline)
        if base.item_name(item) == MATTE_NAME
    ]
    return sorted(rows, key=lambda row: (int(row.get("track_index") or 0), int(row.get("start") or 0)))


def verify_occlusion(timeline: Any) -> Dict[str, Any]:
    rows = occlusion_inventory(timeline)
    max_caption = caption_track_max(timeline)
    expected_start, expected_end = MATTE_RANGE
    ok = bool(
        len(rows) == 1
        and int(rows[0].get("track_index") or 0) > max_caption
        and int(rows[0].get("start") or -1) == expected_start
        and int(rows[0].get("end") or -1) == expected_end
        and int(rows[0].get("duration") or -1) == MATTE_DURATION
        and str(rows[0].get("media_pool_item_name") or "") == MATTE_NAME
    )
    return {
        "rows": rows,
        "max_caption_track": max_caption,
        "required_layer_order": "foreground_rgba_above_textplus",
        "ok": ok,
    }


def validate_source_matte(timeline: Any) -> Dict[str, Any]:
    rows = occlusion_inventory(timeline)
    expected_start, expected_end = MATTE_RANGE
    ok = bool(
        len(rows) == 1
        and int(rows[0].get("start") or -1) == expected_start
        and int(rows[0].get("end") or -1) == expected_end
        and int(rows[0].get("duration") or -1) == MATTE_DURATION
        and str(rows[0].get("media_pool_item_name") or "") == MATTE_NAME
    )
    return {"rows": rows, "ok": ok}


def validate_asset_hashes(root: Path, command: Mapping[str, Any]) -> Dict[str, Any]:
    config = command.get("occlusion")
    if not isinstance(config, Mapping):
        raise ValueError("occlusion_config")
    hashes = config.get("asset_hashes")
    if not isinstance(hashes, Mapping) or len(hashes) != 6:
        raise ValueError("asset_hashes")
    rows = []
    for relative, expected in sorted(hashes.items()):
        path = root / str(relative)
        if not path.is_file():
            raise RuntimeError(f"asset_missing:{relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        matched = actual == str(expected)
        rows.append({"path": str(relative), "expected": str(expected), "actual": actual, "matched": matched, "size": path.stat().st_size})
        if not matched or path.stat().st_size <= 0:
            raise RuntimeError(f"asset_hash:{relative}")
    return {"rows": rows, "verified_count": len(rows), "ok": True}


def ensure_occlusion_above_text(media_pool: Any, timeline: Any) -> Dict[str, Any]:
    before = occlusion_inventory(timeline)
    if len(before) != 1:
        return {"ok": False, "mutated": False, "error": f"matte_count:{len(before)}", "before": before}
    if verify_occlusion(timeline)["ok"]:
        return {"ok": True, "mutated": False, "idempotent_noop": True, "before": before, "after": before}

    old_track, item = next(
        (int(track), item)
        for track, item in base.all_video_items(timeline)
        if base.item_name(item) == MATTE_NAME
    )
    summary = base.item_summary(old_track, item)
    if (
        int(summary.get("start") or -1),
        int(summary.get("end") or -1),
        int(summary.get("duration") or -1),
        str(summary.get("media_pool_item_name") or ""),
    ) != (MATTE_RANGE[0], MATTE_RANGE[1], MATTE_DURATION, MATTE_NAME):
        return {"ok": False, "mutated": False, "error": "matte_preimage", "before": before}

    media_item = base.safe_value(item, "GetMediaPoolItem", default=None)
    if media_item is None:
        return {"ok": False, "mutated": False, "error": "matte_media_pool_item", "before": before}

    target_track = caption_track_max(timeline) + 1
    deletion = base.delete_items(timeline, [item])
    time.sleep(0.15)
    if not deletion.get("ok") or occlusion_inventory(timeline):
        return {"ok": False, "mutated": True, "error": "matte_delete", "deletion": deletion}

    track_setup = base.ensure_video_tracks(timeline, target_track)
    if not track_setup.get("ok"):
        return {"ok": False, "mutated": True, "error": "matte_track_setup", "track_setup": track_setup}

    carrier = {"media_pool_item": media_item, "source_start": 0}
    spec = {
        "cue_id": "foreground_rgba",
        "name": MATTE_NAME,
        "text": "",
        "target_range": [MATTE_RANGE[0], MATTE_RANGE[1]],
        "target_track": target_track,
    }
    append = v6.append_batch_by_placement(media_pool, timeline, carrier, [spec])
    after = occlusion_inventory(timeline)
    verification = verify_occlusion(timeline)
    return {
        "ok": bool(append.get("ok") and verification.get("ok")),
        "mutated": True,
        "idempotent_noop": False,
        "source_track": old_track,
        "target_track": target_track,
        "deletion": deletion,
        "track_setup": track_setup,
        "append": base.json_safe({key: value for key, value in append.items() if key != "assigned"}),
        "after": after,
        "verification": verification,
    }


def cleanup_before_save(project_manager: Any, project: Any, media_pool: Any, source: Any, target_created: bool) -> Dict[str, Any]:
    result: Dict[str, Any] = {"errors": [], "save_call_count": 0}
    try:
        if source is not None and project is not None:
            selected, call = base.direct_call(project, "SetCurrentTimeline", source)
            result["restore_source"] = call
            if not selected:
                result["errors"].append("restore_source")
        target = base.find_timeline(project, TARGET_TIMELINE_NAME) if project is not None else None
        if target_created and target is not None and media_pool is not None:
            deleted, call = base.direct_call(media_pool, "DeleteTimelines", [target])
            result["delete_target"] = call
            if not deleted:
                result["errors"].append("delete_target")
        if target_created and project_manager is not None:
            save = base.save_project(project_manager)
            result["save"] = save
            result["save_call_count"] = 1
            if not save.get("success"):
                result["errors"].append("save_cleanup")
    except BaseException as exc:
        result["errors"].append(base.compact_exception(exc))
        result["traceback"] = traceback.format_exc()
    result["ok"] = not result["errors"]
    return result


def run(resolve: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    root = base.repository_root()
    command = context.get("command") if isinstance(context, dict) else None
    if not isinstance(command, dict):
        raise ValueError("command")
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    if command.get("task_id") != TASK_ID or command.get("mode") != MODE or not run_id:
        raise ValueError("command_identity")

    report_dir = base.relative_path(root, command.get("artifacts_dir"))
    report_dir.mkdir(parents=True, exist_ok=True)
    report: Dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "ok": False,
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "target_timeline_name": TARGET_TIMELINE_NAME,
        "save_call_count": 0,
        "resolve_invocation_contract": 1,
        "caption_mutation_count": 0,
        "occlusion_mutation_count": 0,
        "final_textplus_count": 0,
        "source_timeline_unchanged": False,
        "caption_baseline_unchanged": False,
        "persistent_readback_ok": False,
        "idempotency_ok": False,
        "visual_approval_required": True,
        "further_rollout_authorized": False,
        "failures": [],
    }

    project_manager = project = media_pool = None
    source = None
    target_created = False
    saved = False

    try:
        source_contract = base.verify_source_contract(root, command)
        base.write_json(report_dir / "source_contract_verification.json", source_contract)
        assets = validate_asset_hashes(root, command)
        base.write_json(report_dir / "approved_rgba_asset_verification.json", assets)

        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        if base.find_timeline(project, TARGET_TIMELINE_NAME) is not None:
            raise RuntimeError("target_exists")

        source_uid = base.timeline_unique_id(source)
        source_caption_before = caption_snapshot(source)
        source_inventory_before = stable_inventory(source)
        source_nonmatte_before = stable_inventory(source, exclude_matte=True)
        source_matte = validate_source_matte(source)
        if not source_matte["ok"]:
            raise RuntimeError("source_matte")
        if full.track_two_item_names(source):
            raise RuntimeError("source_v2_not_empty")

        base.write_json(
            report_dir / "occlusion_preflight.json",
            {
                "schema_version": 1,
                "task_id": TASK_ID,
                "run_id": run_id,
                "resolve_calls": resolve_calls,
                "source_unique_id": source_uid,
                "source_caption_snapshot": source_caption_before,
                "source_matte": source_matte,
                "source_nonmatte_inventory": source_nonmatte_before,
                "expected_textplus_count": EXPECTED_TEXTPLUS_COUNT,
                "ok": True,
            },
        )

        duplicate_value, duplicate_call = base.direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
        target = duplicate_value if duplicate_value is not None else base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target is None:
            raise RuntimeError("duplicate_timeline")
        target_created = True
        selected, select_call = base.direct_call(project, "SetCurrentTimeline", target)
        if not selected:
            raise RuntimeError("select_target")

        target_caption_duplicate = caption_snapshot(target)
        if not caption_snapshots_equal(source_caption_before, target_caption_duplicate):
            raise RuntimeError("duplicate_caption_regression")
        if stable_inventory(target, exclude_matte=True) != source_nonmatte_before:
            raise RuntimeError("duplicate_nonmatte_regression")

        first = ensure_occlusion_above_text(media_pool, target)
        target_caption_after_first = caption_snapshot(target)
        first_caption_unchanged = caption_snapshots_equal(target_caption_duplicate, target_caption_after_first)
        first_nonmatte_unchanged = stable_inventory(target, exclude_matte=True) == source_nonmatte_before
        if not first.get("ok") or not first.get("mutated") or not first_caption_unchanged or not first_nonmatte_unchanged:
            raise RuntimeError("occlusion_first_application")

        second = ensure_occlusion_above_text(media_pool, target)
        target_caption_after_second = caption_snapshot(target)
        second_caption_unchanged = caption_snapshots_equal(target_caption_after_first, target_caption_after_second)
        second_nonmatte_unchanged = stable_inventory(target, exclude_matte=True) == source_nonmatte_before
        if (
            not second.get("ok")
            or second.get("mutated")
            or second.get("idempotent_noop") is not True
            or not second_caption_unchanged
            or not second_nonmatte_unchanged
        ):
            raise RuntimeError("occlusion_idempotency")

        pre_save_occlusion = verify_occlusion(target)
        if not pre_save_occlusion["ok"]:
            raise RuntimeError("occlusion_pre_save_readback")

        base.write_json(
            report_dir / "occlusion_application.json",
            {
                "duplicate_call": duplicate_call,
                "select_call": select_call,
                "first_application": first,
                "second_application": second,
                "checks": {
                    "duplicate_caption_baseline_exact": True,
                    "duplicate_nonmatte_inventory_exact": True,
                    "first_caption_baseline_unchanged": first_caption_unchanged,
                    "first_nonmatte_inventory_unchanged": first_nonmatte_unchanged,
                    "second_is_idempotent_noop": second.get("idempotent_noop") is True and second.get("mutated") is False,
                    "second_caption_baseline_unchanged": second_caption_unchanged,
                    "second_nonmatte_inventory_unchanged": second_nonmatte_unchanged,
                    "occlusion_above_all_caption_tracks": pre_save_occlusion["ok"],
                },
                "caption_snapshot_before": target_caption_duplicate,
                "caption_snapshot_after": target_caption_after_second,
                "occlusion": pre_save_occlusion,
                "ok": True,
            },
        )

        save = base.save_project(project_manager)
        report["save_call_count"] = 1
        saved = True
        if not save.get("success"):
            raise RuntimeError("save")

        project_manager, project, media_pool, reacquire_calls = base.get_project(resolve)
        source_after = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        target_after = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if source_after is None or target_after is None:
            raise RuntimeError("reacquire")

        source_caption_after = caption_snapshot(source_after)
        target_caption_persistent = caption_snapshot(target_after)
        target_occlusion_persistent = verify_occlusion(target_after)

        checks = {
            "source_timeline_unique_id_unchanged": base.timeline_unique_id(source_after) == source_uid,
            "source_full_inventory_unchanged": stable_inventory(source_after) == source_inventory_before,
            "source_caption_baseline_unchanged": caption_snapshots_equal(source_caption_before, source_caption_after),
            "target_caption_baseline_unchanged": caption_snapshots_equal(source_caption_before, target_caption_persistent),
            "target_nonmatte_inventory_unchanged": stable_inventory(target_after, exclude_matte=True) == source_nonmatte_before,
            "occlusion_above_all_caption_tracks": target_occlusion_persistent["ok"],
            "physical_textplus_count": target_caption_persistent["count"] == EXPECTED_TEXTPLUS_COUNT,
            "v2_empty": not full.track_two_item_names(target_after),
            "one_save": report["save_call_count"] == 1,
            "idempotency_proven_pre_save": second.get("idempotent_noop") is True and second.get("mutated") is False,
        }
        persistent = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "reacquire_calls": reacquire_calls,
            "save": save,
            "source_caption_snapshot_before": source_caption_before,
            "source_caption_snapshot_after": source_caption_after,
            "target_caption_snapshot": target_caption_persistent,
            "occlusion": target_occlusion_persistent,
            "checks": checks,
            "visual_approval_required": True,
            "further_rollout_authorized": False,
            "ok": all(checks.values()),
        }
        base.write_json(report_dir / "persistent_readback.json", persistent)
        if not persistent["ok"]:
            # The single save has already happened. Deliberately do not make a
            # second save/cleanup mutation; retain the isolated target as failure
            # evidence and require manual deletion before any later task.
            raise RuntimeError("persistent_readback")

        report.update(
            {
                "ok": True,
                "occlusion_mutation_count": 1,
                "final_textplus_count": EXPECTED_TEXTPLUS_COUNT,
                "source_timeline_unchanged": True,
                "caption_baseline_unchanged": True,
                "persistent_readback_ok": True,
                "idempotency_ok": True,
                "occlusion_target_track": int(target_occlusion_persistent["rows"][0]["track_index"]),
                "target_timeline_kept": True,
            }
        )
        return report
    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc))
        report["traceback"] = traceback.format_exc()
        if target_created and not saved and project_manager is not None and project is not None and media_pool is not None:
            cleanup = cleanup_before_save(project_manager, project, media_pool, source, target_created)
            base.write_json(report_dir / "failure_cleanup.json", cleanup)
            report["save_call_count"] = int(cleanup.get("save_call_count") or 0)
            report["failure_cleanup_ok"] = cleanup.get("ok") is True
        elif saved:
            report["post_save_failure_target_retained"] = True
            report["manual_delete_required_before_next_task"] = True
        return report
