"""Repair only the two oversized physical `the` captions after motion/fade V1.

The user visually accepted the motion/fade rollout except for the popping `the`.
Later direct source-metric authority proves that the two physical `the` instances
(sub_077 and sub_079) are ~0.09 Text+ Size, while the accepted motion/fade
source still carries ~0.25 values. This module duplicates the motion/fade V1
timeline and mutates only Size for those two captions. Every other caption
property, clip range, track, animation key topology, and the accepted V4
occlusion layer is frozen.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

TASK_ID = "DZSQH7AUHJT_CAPTION_THE_SIZE_POP_FIX_V1"
MODE = "CAPTION_THE_SIZE_POP_FIX_V1"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/caption_the_size_pop_fix_v1.py"
SOURCE_TIMELINE_NAME = (
    "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_"
    "repair_metrics_v1_occlusion_complete_v4_motion_fade_v1"
)
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_the_size_fix_v1"
SIZE_PLAN_RELATIVE_PATH = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_font_size_plan_step_3B_2.json"
SIZE_PLAN_RAW_SHA256 = "40f6c601f2f72b73c50dc58e942f6b54cdb032163a73d90a58185c9249f61089"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
EXPECTED_TEXTPLUS_COUNT = 114
EXPECTED_V4_MATTE = "VC_OCCLUSION_PIXEL_RESTORE_matte_span_0001_v4_sub_0052"
EXPECTED_V4_RANGE = [426, 454]
TOLERANCE = 1e-5

TARGETS: Dict[str, Dict[str, Any]] = {
    "VC_TEXTPLUS_0077_sub_077": {
        "cue_id": "sub_077",
        "expected_start": 612,
        "expected_end": 626,
        "expected_track": 3,
        "expected_pre_size": 0.257314286,
        "target_size": 0.089954170778,
        "authority_event": "style_event_sub_0077",
    },
    "VC_TEXTPLUS_0079_sub_079": {
        "cue_id": "sub_079",
        "expected_start": 635,
        "expected_end": 642,
        "expected_track": 3,
        "expected_pre_size": 0.247157143,
        "target_size": 0.090976377264,
        "authority_event": "style_event_sub_0079",
    },
}


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
motion = _load("vc_motion_fade_for_the_size_fix", HERE / "caption_motion_fade_application_v1.py")
V4 = motion.V4
V1 = motion.V1
base = motion.base
full = motion.full
visual = motion.visual


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def scalar_matches(actual: Any, expected: float, tolerance: float = TOLERANCE) -> bool:
    try:
        return abs(float(actual) - float(expected)) <= tolerance
    except (TypeError, ValueError):
        return False


def snapshot_map(snapshot: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    rows = snapshot.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError("snapshot_rows")
    result = {str(row.get("name") or ""): row for row in rows if isinstance(row, Mapping)}
    if len(result) != EXPECTED_TEXTPLUS_COUNT:
        raise RuntimeError(f"snapshot_map_count:{len(result)}")
    return result


def property_values(snapshot_row: Mapping[str, Any], name: str) -> list[Any]:
    prop = (snapshot_row.get("properties") or {}).get(name) or {}
    values = prop.get("values")
    return list(values) if isinstance(values, list) else []


def find_item(timeline: Any, name: str) -> tuple[int, Any]:
    rows = [(int(track), item) for track, item in base.all_video_items(timeline) if base.item_name(item) == name]
    if len(rows) != 1:
        raise RuntimeError(f"target_item_count:{name}:{len(rows)}")
    return rows[0]


def text_tool(item: Any) -> Any:
    comp = base.get_comp(item)
    tool = base.get_text_tool(comp)
    if comp is None or tool is None:
        raise RuntimeError(f"text_tool:{base.item_name(item)}")
    return tool


def verify_size_plan(plan: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    if plan.get("ok") is not True or plan.get("plan_item_count") != 116:
        raise ValueError("size_plan_identity")
    items = plan.get("items")
    if not isinstance(items, list):
        raise ValueError("size_plan_items")
    by_name = {str(row.get("name") or ""): row for row in items if isinstance(row, Mapping)}
    authority: Dict[str, Dict[str, Any]] = {}
    for name, expected in TARGETS.items():
        row = by_name.get(name)
        if not isinstance(row, Mapping):
            raise ValueError(f"size_plan_target_missing:{name}")
        if row.get("cue_id") != expected["cue_id"]:
            raise ValueError(f"size_plan_cue:{name}")
        if row.get("source_metrics", {}).get("source") != "caption_style_event":
            raise ValueError(f"size_plan_source:{name}")
        if not scalar_matches(row.get("target_size"), expected["target_size"], tolerance=1e-12):
            raise ValueError(f"size_plan_value:{name}")
        source_event = row.get("source_metrics", {}).get("bbox")
        if not isinstance(source_event, list) or len(source_event) != 4:
            raise ValueError(f"size_plan_bbox:{name}")
        authority[name] = dict(row)
    return authority


def verify_source_preimage(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    rows = snapshot_map(snapshot)
    checks: Dict[str, Any] = {}
    for name, expected in TARGETS.items():
        row = rows.get(name)
        if not isinstance(row, Mapping):
            raise RuntimeError(f"preimage_missing:{name}")
        summary = row.get("summary") if isinstance(row.get("summary"), Mapping) else {}
        if (
            int(summary.get("start") or -1) != expected["expected_start"]
            or int(summary.get("end") or -1) != expected["expected_end"]
            or int(summary.get("track_index") or -1) != expected["expected_track"]
        ):
            raise RuntimeError(f"preimage_range:{name}")
        values = property_values(row, "Size")
        if len(values) != expected["expected_end"] - expected["expected_start"]:
            raise RuntimeError(f"preimage_size_length:{name}")
        if not all(scalar_matches(value, expected["expected_pre_size"]) for value in values):
            raise RuntimeError(f"preimage_size_value:{name}")
        prop = (row.get("properties") or {}).get("Size") or {}
        if prop.get("connected") is not True or not prop.get("keyframes"):
            raise RuntimeError(f"preimage_size_topology:{name}")
        checks[name] = {
            "start": summary.get("start"),
            "end": summary.get("end"),
            "track": summary.get("track_index"),
            "pre_size": expected["expected_pre_size"],
            "target_size": expected["target_size"],
            "keyframe_count": len(prop.get("keyframes") or {}),
        }
    return {"ok": True, "targets": checks}


def expected_sizes(snapshot: Mapping[str, Any]) -> Dict[str, list[float]]:
    rows = snapshot_map(snapshot)
    result: Dict[str, list[float]] = {}
    for name, expected in TARGETS.items():
        row = rows[name]
        summary = row.get("summary") or {}
        duration = int(summary.get("end")) - int(summary.get("start"))
        result[name] = [float(expected["target_size"])] * duration
    return result


def size_series_matches(tool: Any, expected: Sequence[float]) -> bool:
    return all(scalar_matches(base.read_input(tool, "Size", local), value) for local, value in enumerate(expected))


def write_size_dense(tool: Any, expected: Sequence[float]) -> Dict[str, Any]:
    input_object = base.find_input(tool, "Size")
    if input_object is None or visual.connected_output(input_object) is None:
        return {"ok": False, "write_count": 0, "error": "size_modifier_missing"}
    rows = []
    for local, expected_value in enumerate(expected):
        write = visual.write_key(tool, "Size", local, float(expected_value))
        rows.append({"local_frame": local, "expected": float(expected_value), "write": write})
        if not write.get("ok"):
            break
    ok = len(rows) == len(expected) and all(row["write"].get("ok") for row in rows) and size_series_matches(tool, expected)
    return {"ok": ok, "write_count": len(rows), "rows": rows}


def apply_expected(timeline: Any, expected: Mapping[str, Sequence[float]]) -> Dict[str, Any]:
    rows = []
    write_count = 0
    for name in sorted(expected):
        track, item = find_item(timeline, name)
        if track != int(TARGETS[name]["expected_track"]):
            return {"ok": False, "write_count": write_count, "rows": rows, "error": f"track:{name}:{track}"}
        tool = text_tool(item)
        series = list(expected[name])
        if size_series_matches(tool, series):
            rows.append({"name": name, "mutated": False, "write_count": 0, "ok": True})
            continue
        result = write_size_dense(tool, series)
        rows.append({"name": name, "mutated": True, **result})
        write_count += int(result.get("write_count") or 0)
        if not result.get("ok"):
            return {"ok": False, "write_count": write_count, "rows": rows}
    return {
        "ok": True,
        "write_count": write_count,
        "rows": rows,
        "mutated_property_count": sum(1 for row in rows if row.get("mutated")),
    }


def verify_snapshot(source: Mapping[str, Any], actual: Mapping[str, Any], expected: Mapping[str, Sequence[float]]) -> Dict[str, Any]:
    source_rows = snapshot_map(source)
    actual_rows = snapshot_map(actual)
    failures = []
    for name, source_row in source_rows.items():
        row = actual_rows.get(name)
        if row is None:
            failures.append(f"missing:{name}")
            continue
        if row.get("summary") != source_row.get("summary"):
            failures.append(f"summary:{name}")
        if row.get("clip_enabled") != source_row.get("clip_enabled"):
            failures.append(f"clip_enabled:{name}")
        source_props = source_row.get("properties") or {}
        actual_props = row.get("properties") or {}
        for prop_name, source_prop in source_props.items():
            actual_prop = actual_props.get(prop_name)
            if name not in expected or prop_name != "Size":
                if actual_prop != source_prop:
                    failures.append(f"frozen:{name}:{prop_name}")
                continue
            if not isinstance(actual_prop, Mapping):
                failures.append(f"size_missing:{name}")
                continue
            values = actual_prop.get("values")
            wanted = list(expected[name])
            if not isinstance(values, list) or len(values) != len(wanted):
                failures.append(f"size_length:{name}")
                continue
            if not all(scalar_matches(value, wanted[i]) for i, value in enumerate(values)):
                failures.append(f"size_value:{name}")
            # Topology and metadata stay frozen; only Size values may differ.
            for field in ("exists", "data_type", "connected", "keyframes"):
                if actual_prop.get(field) != source_prop.get(field):
                    failures.append(f"size_structure:{name}:{field}")
    return {"ok": not failures, "failure_count": len(failures), "failures": failures[:200]}


def verify_source_contract(root: Path, command: Mapping[str, Any]) -> Dict[str, Any]:
    contract = command.get("source_contract")
    if not isinstance(contract, Mapping) or contract.get("algorithm") != SOURCE_HASH_ALGORITHM:
        raise ValueError("source_contract")
    rows = []
    for relative, expected in sorted((contract.get("hashes") or {}).items()):
        path = root / str(relative)
        if not path.is_file():
            raise ValueError(f"source_missing:{relative}")
        actual = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()
        matched = actual == expected
        rows.append({"path": relative, "expected": expected, "actual": actual, "matched": matched})
        if not matched:
            raise ValueError(f"source_hash:{relative}")
    return {"algorithm": SOURCE_HASH_ALGORITHM, "rows": rows, "verified_count": len(rows), "ok": True}


def delete_timeline(media_pool: Any, timeline: Any) -> Dict[str, Any]:
    value, call = base.direct_call(media_pool, "DeleteTimelines", [timeline])
    return {"ok": bool(value), "call": call}


def cleanup(project_manager: Any, project: Any, media_pool: Any, source: Any, target_created: bool) -> Dict[str, Any]:
    result: Dict[str, Any] = {"errors": [], "save_call_count": 0}
    try:
        if source is not None:
            selected, call = base.direct_call(project, "SetCurrentTimeline", source)
            result["restore_source"] = call
            if not selected:
                result["errors"].append("restore_source")
        target = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target_created and target is not None:
            deletion = delete_timeline(media_pool, target)
            result["delete_target"] = deletion
            if not deletion.get("ok"):
                result["errors"].append("delete_target")
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
    if not run_id or command.get("task_id") != TASK_ID or command.get("mode") != MODE or command.get("module") != MODULE_RELATIVE_PATH:
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
        "final_textplus_count": None,
        "target_caption_count": len(TARGETS),
        "size_key_write_count": 0,
        "mutated_property_count": 0,
        "caption_recreation_count": 0,
        "center_write_count": 0,
        "opacity_write_count": 0,
        "style_write_count": 0,
        "timing_track_mutation_count": 0,
        "occlusion_mutation_count": 0,
        "save_call_count": 0,
        "resolve_invocation_contract": 1,
        "visual_approval_required": True,
        "further_rollout_authorized": False,
        "failures": [],
    }
    project_manager = project = media_pool = source = None
    target_created = False
    saved = False
    try:
        source_contract = verify_source_contract(root, command)
        base.write_json(report_dir / "source_contract_verification.json", source_contract)
        plan_path = root / SIZE_PLAN_RELATIVE_PATH
        if hashlib.sha256(plan_path.read_bytes()).hexdigest() != SIZE_PLAN_RAW_SHA256:
            raise RuntimeError("size_plan_hash")
        authority = verify_size_plan(load_json(plan_path))
        config = command.get("the_size_fix") if isinstance(command.get("the_size_fix"), Mapping) else {}
        if config.get("source_timeline_name") != SOURCE_TIMELINE_NAME or config.get("target_timeline_name") != TARGET_TIMELINE_NAME:
            raise RuntimeError("config_timeline")
        if config.get("target_sizes") != {name: TARGETS[name]["target_size"] for name in sorted(TARGETS)}:
            raise RuntimeError("config_target_sizes")

        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        if base.find_timeline(project, TARGET_TIMELINE_NAME) is not None:
            raise RuntimeError("target_exists")
        source_uid = base.timeline_unique_id(source)
        source_snapshot = V1.caption_snapshot(source)
        if source_snapshot.get("count") != EXPECTED_TEXTPLUS_COUNT:
            raise RuntimeError("source_caption_count")
        if full.track_two_item_names(source):
            raise RuntimeError("source_v2_not_empty")
        source_occ = V4.verify_v4_occlusion(source)
        if (
            not source_occ.get("ok")
            or [source_occ["rows"][0].get("start"), source_occ["rows"][0].get("end")] != EXPECTED_V4_RANGE
            or source_occ["rows"][0].get("name") != EXPECTED_V4_MATTE
        ):
            raise RuntimeError("source_v4_occlusion")
        preimage = verify_source_preimage(source_snapshot)
        source_inventory = V1.stable_inventory(source)
        expected = expected_sizes(source_snapshot)
        base.write_json(report_dir / "the_size_fix_preflight.json", {
            "resolve_calls": resolve_calls,
            "source_unique_id": source_uid,
            "source_caption_snapshot_sha256": source_snapshot.get("sha256"),
            "source_v4_occlusion": source_occ,
            "source_preimage": preimage,
            "authority": {name: {"cue_id": row.get("cue_id"), "target_size": row.get("target_size"), "source_metrics": row.get("source_metrics")} for name, row in authority.items()},
            "frozen_properties": [prop for prop in V1.CAPTION_PROPERTIES if prop != "Size"],
            "ok": True,
        })

        duplicate, duplicate_call = base.direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
        target = duplicate if duplicate is not None else base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target is None:
            raise RuntimeError("duplicate_target")
        target_created = True
        selected, select_call = base.direct_call(project, "SetCurrentTimeline", target)
        if not selected:
            raise RuntimeError("select_target")
        duplicate_snapshot = V1.caption_snapshot(target)
        if not V1.caption_snapshots_equal(source_snapshot, duplicate_snapshot):
            raise RuntimeError("duplicate_caption_regression")
        if V1.stable_inventory(target) != source_inventory or not V4.verify_v4_occlusion(target).get("ok"):
            raise RuntimeError("duplicate_inventory_regression")

        first = apply_expected(target, expected)
        if not first.get("ok"):
            raise RuntimeError("first_application")
        after_first = V1.caption_snapshot(target)
        first_verify = verify_snapshot(source_snapshot, after_first, expected)
        if not first_verify.get("ok"):
            raise RuntimeError("first_regression_guard")
        if V1.stable_inventory(target) != source_inventory or not V4.verify_v4_occlusion(target).get("ok"):
            raise RuntimeError("first_noncaption_regression")

        second = apply_expected(target, expected)
        if not second.get("ok") or second.get("write_count") != 0 or second.get("mutated_property_count") != 0:
            raise RuntimeError("idempotency")
        after_second = V1.caption_snapshot(target)
        second_verify = verify_snapshot(source_snapshot, after_second, expected)
        if not second_verify.get("ok"):
            raise RuntimeError("second_regression_guard")
        source_before_save = V1.caption_snapshot(source)
        if not V1.caption_snapshots_equal(source_snapshot, source_before_save):
            raise RuntimeError("source_mutated_pre_save")

        base.write_json(report_dir / "the_size_fix_application.json", {
            "duplicate_call": duplicate_call,
            "select_call": select_call,
            "first_application": first,
            "first_verification": first_verify,
            "second_application": second,
            "second_verification": second_verify,
            "target_caption_snapshot_sha256": after_second.get("sha256"),
            "v4_occlusion": V4.verify_v4_occlusion(target),
            "ok": True,
        })

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
        source_after_snapshot = V1.caption_snapshot(source_after)
        target_after_snapshot = V1.caption_snapshot(target_after)
        persistent_verify = verify_snapshot(source_snapshot, target_after_snapshot, expected)
        checks = {
            "source_unique_id_unchanged": base.timeline_unique_id(source_after) == source_uid,
            "source_caption_unchanged": V1.caption_snapshots_equal(source_snapshot, source_after_snapshot),
            "source_inventory_unchanged": V1.stable_inventory(source_after) == source_inventory,
            "target_expected_state": persistent_verify.get("ok") is True,
            "target_inventory_unchanged": V1.stable_inventory(target_after) == source_inventory,
            "target_v4_occlusion_preserved": V4.verify_v4_occlusion(target_after).get("ok") is True,
            "textplus_114": target_after_snapshot.get("count") == EXPECTED_TEXTPLUS_COUNT,
            "v2_empty": not full.track_two_item_names(target_after),
            "one_save": report["save_call_count"] == 1,
            "idempotent_second_zero_write": second.get("write_count") == 0 and second.get("mutated_property_count") == 0,
            "exact_two_size_properties_mutated": first.get("mutated_property_count") == 2,
            "exact_21_size_keys_written": first.get("write_count") == 21,
            "no_caption_recreation": True,
            "no_center_opacity_style_timing_or_occlusion_write": True,
        }
        persistent = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "save": save,
            "reacquire_calls": reacquire_calls,
            "checks": checks,
            "persistent_verification": persistent_verify,
            "target_caption_snapshot_sha256": target_after_snapshot.get("sha256"),
            "source_caption_snapshot_sha256": source_after_snapshot.get("sha256"),
            "visual_approval_required": True,
            "further_rollout_authorized": False,
            "ok": all(checks.values()),
        }
        base.write_json(report_dir / "persistent_readback.json", persistent)
        if not persistent["ok"]:
            raise RuntimeError("persistent_readback")

        report.update({
            "ok": True,
            "final_textplus_count": EXPECTED_TEXTPLUS_COUNT,
            "size_key_write_count": int(first.get("write_count") or 0),
            "mutated_property_count": int(first.get("mutated_property_count") or 0),
            "persistent_readback_ok": True,
            "idempotency_ok": True,
            "source_timeline_unchanged": True,
            "v4_occlusion_preserved": True,
            "motion_fade_source_preserved_except_target_size": True,
            "target_timeline_kept": True,
        })
        return report
    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc))
        report["traceback"] = traceback.format_exc()
        if not saved and project_manager is not None and project is not None and media_pool is not None:
            result = cleanup(project_manager, project, media_pool, source, target_created)
            base.write_json(report_dir / "failure_cleanup.json", result)
            report["save_call_count"] = int(result.get("save_call_count") or 0)
            report["failure_cleanup_ok"] = result.get("ok") is True
            report["failed_target_retained"] = False if result.get("ok") else None
        elif saved:
            report["post_save_failure_target_retained"] = True
        return report
