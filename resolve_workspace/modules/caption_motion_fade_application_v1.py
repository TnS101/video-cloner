"""Apply only source-proven caption Center motion/exits and protected opacity fades.

The source is the human-approved final occlusion V4 timeline. The module never
recreates captions. It duplicates that accepted timeline, freezes every caption
property, then authorizes only:
- Center on authority-listed dynamic/exit targets;
- Opacity1/2/3 on the 17 protected V4 source-pixel fade targets.

For an authorized property, the full local-frame series is rebuilt from the
accepted source values with authority frames overlaid. This preserves all
non-authority frames while allowing a modifier/key topology change only on the
explicitly targeted property.
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

TASK_ID = "DZSQH7AUHJT_CAPTION_MOTION_FADE_APPLICATION_V1"
MODE = "CAPTION_MOTION_FADE_APPLICATION_V1"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/caption_motion_fade_application_v1.py"
AUTHORITY_RELATIVE_PATH = "artifacts/DZSQH7AUHJT_CAPTION_MOTION_FADE_APPLICATION_V1/caption_motion_fade_authority_v1.json"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1_occlusion_complete_v4"
TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_motion_fade_v1"
EXPECTED_TEXTPLUS_COUNT = 114
EXPECTED_CENTER_TARGETS = 7
EXPECTED_OPACITY_TARGETS = 17
EXPECTED_V4_MATTE = "VC_OCCLUSION_PIXEL_RESTORE_matte_span_0001_v4_sub_0052"
EXPECTED_V4_RANGE = [426, 454]
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
OPACITY_INPUTS = ("Opacity1", "Opacity2", "Opacity3")
ALLOWED_PROPERTIES = {"Center", *OPACITY_INPUTS}
TOLERANCE = 1e-4
POINT_TOLERANCE = 0.0025


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
V4 = _load("vc_final_occ_v4_for_motion_fade", HERE / "final_occlusion_composition_v4.py")
V1 = V4.V1
base = V4.base
full = V4.full
visual = _load("vc_visual_correction_for_motion_fade", HERE / "step_3D_visual_instance_correction.py")


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def _norm(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, str) or isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 9) if math.isfinite(value) else str(value)
    if isinstance(value, Mapping):
        return {str(k): _norm(v) for k, v in sorted(value.items(), key=lambda row: str(row[0]))}
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    return _norm(base.json_safe(value))


def point(value: Any) -> list[float] | None:
    return base.normalize_point(value)


def point_matches(actual: Any, expected: Sequence[float]) -> bool:
    a = point(actual)
    return bool(a is not None and len(expected) >= 2 and abs(a[0] - float(expected[0])) <= POINT_TOLERANCE and abs(a[1] - float(expected[1])) <= POINT_TOLERANCE)


def scalar_matches(actual: Any, expected: float) -> bool:
    try:
        return abs(float(actual) - float(expected)) <= TOLERANCE
    except (TypeError, ValueError):
        return False


def property_values(snapshot_row: Mapping[str, Any], name: str) -> list[Any]:
    prop = (snapshot_row.get("properties") or {}).get(name) or {}
    values = prop.get("values")
    return list(values) if isinstance(values, list) else []


def snapshot_map(snapshot: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    rows = snapshot.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError("snapshot_rows")
    result = {str(row.get("name") or ""): row for row in rows if isinstance(row, Mapping)}
    if len(result) != EXPECTED_TEXTPLUS_COUNT:
        raise RuntimeError(f"snapshot_map_count:{len(result)}")
    return result


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


def expected_center_series(source_row: Mapping[str, Any], update: Mapping[str, Any]) -> list[list[float]]:
    raw = property_values(source_row, "Center")
    expected = []
    for value in raw:
        p = point(value)
        if p is None:
            raise RuntimeError(f"source_center:{source_row.get('name')}")
        expected.append([float(p[0]), float(p[1])])
    summary = source_row.get("summary") if isinstance(source_row.get("summary"), Mapping) else {}
    start = int(summary.get("start") or -1)
    end = int(summary.get("end") or -1)
    if start < 0 or end <= start or len(expected) != end - start:
        raise RuntimeError(f"center_source_range:{source_row.get('name')}")
    applied = 0
    for key in update.get("position_keys") or []:
        frame = int(key.get("timeline_frame") or -1)
        if not start <= frame < end:
            continue
        value = key.get("value")
        if not isinstance(value, list) or len(value) != 2:
            raise RuntimeError(f"center_authority_value:{source_row.get('name')}:{frame}")
        expected[frame - start] = [float(value[0]), float(value[1])]
        applied += 1
    if applied == 0:
        raise RuntimeError(f"center_authority_empty:{source_row.get('name')}")
    return expected


def expected_opacity_series(source_row: Mapping[str, Any], update: Mapping[str, Any], input_name: str) -> list[float] | None:
    raw = property_values(source_row, input_name)
    if not raw:
        return None
    values: list[float] = []
    for value in raw:
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            raise RuntimeError(f"source_opacity:{source_row.get('name')}:{input_name}")
    summary = source_row.get("summary") if isinstance(source_row.get("summary"), Mapping) else {}
    start = int(summary.get("start") or -1)
    end = int(summary.get("end") or -1)
    if len(values) != end - start:
        raise RuntimeError(f"opacity_source_range:{source_row.get('name')}:{input_name}")
    factors = update.get("opacity_factors")
    if not isinstance(factors, list) or len(factors) != end - start:
        raise RuntimeError(f"opacity_authority_dense:{source_row.get('name')}")
    base_value = max(values)
    expected = list(values)
    for local, row in enumerate(factors):
        if int(row.get("timeline_frame") or -1) != start + local:
            raise RuntimeError(f"opacity_frame:{source_row.get('name')}:{local}")
        factor = float(row.get("factor"))
        if not 0.0 <= factor <= 1.0:
            raise RuntimeError(f"opacity_factor:{source_row.get('name')}:{local}")
        expected[local] = base_value * factor
    return expected


def series_matches(tool: Any, input_name: str, expected: Sequence[Any]) -> bool:
    for local, value in enumerate(expected):
        actual = base.read_input(tool, input_name, local)
        if input_name == "Center":
            if not point_matches(actual, value):
                return False
        elif not scalar_matches(actual, float(value)):
            return False
    return True


def write_dense(tool: Any, input_name: str, expected: Sequence[Any]) -> Dict[str, Any]:
    modifier_name = "Path" if input_name == "Center" else "BezierSpline"
    modifier = visual.ensure_modifier(tool, input_name, modifier_name)
    if not modifier.get("ok"):
        return {"ok": False, "input": input_name, "modifier": modifier, "write_count": 0}
    rows = []
    for local, expected_value in enumerate(expected):
        write = visual.write_key(tool, input_name, local, expected_value)
        rows.append({"local_frame": local, "write": write})
        if not write.get("ok"):
            break
    ok = len(rows) == len(expected) and all(row["write"].get("ok") for row in rows) and series_matches(tool, input_name, expected)
    return {"ok": ok, "input": input_name, "modifier": modifier, "write_count": len(rows), "rows": rows}


def build_expected(source_snapshot: Mapping[str, Any], authority: Mapping[str, Any]) -> Dict[str, Dict[str, list[Any]]]:
    rows = snapshot_map(source_snapshot)
    expected: Dict[str, Dict[str, list[Any]]] = {}
    center_updates = list(authority.get("repair_center_updates") or []) + list(authority.get("protected_exit_center_updates") or [])
    if len(center_updates) != EXPECTED_CENTER_TARGETS:
        raise RuntimeError(f"center_authority_count:{len(center_updates)}")
    for update in center_updates:
        name = str(update.get("target_name") or "")
        if name not in rows or name in expected and "Center" in expected[name]:
            raise RuntimeError(f"center_target:{name}")
        expected.setdefault(name, {})["Center"] = expected_center_series(rows[name], update)
    opacity_updates = authority.get("protected_opacity_updates")
    if not isinstance(opacity_updates, list) or len(opacity_updates) != EXPECTED_OPACITY_TARGETS:
        raise RuntimeError("opacity_authority_count")
    for update in opacity_updates:
        name = str(update.get("target_name") or "")
        if name not in rows:
            raise RuntimeError(f"opacity_target:{name}")
        for input_name in OPACITY_INPUTS:
            series = expected_opacity_series(rows[name], update, input_name)
            if series is not None:
                expected.setdefault(name, {})[input_name] = series
    return expected


def verify_snapshot(source: Mapping[str, Any], actual: Mapping[str, Any], expected: Mapping[str, Mapping[str, Sequence[Any]]]) -> Dict[str, Any]:
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
        allowed = expected.get(name, {})
        for prop_name, source_prop in source_props.items():
            actual_prop = actual_props.get(prop_name)
            if prop_name not in allowed:
                if actual_prop != source_prop:
                    failures.append(f"frozen:{name}:{prop_name}")
                continue
            if not isinstance(actual_prop, Mapping):
                failures.append(f"target_property_missing:{name}:{prop_name}")
                continue
            values = actual_prop.get("values")
            wanted = allowed[prop_name]
            if not isinstance(values, list) or len(values) != len(wanted):
                failures.append(f"target_length:{name}:{prop_name}")
                continue
            for local, expected_value in enumerate(wanted):
                actual_value = values[local]
                matched = point_matches(actual_value, expected_value) if prop_name == "Center" else scalar_matches(actual_value, float(expected_value))
                if not matched:
                    failures.append(f"target_value:{name}:{prop_name}:{local}")
                    break
            # Existence/data type are still frozen; only connection/key topology may change.
            for field in ("exists", "data_type"):
                if actual_prop.get(field) != source_prop.get(field):
                    failures.append(f"target_structure:{name}:{prop_name}:{field}")
    return {"ok": not failures, "failure_count": len(failures), "failures": failures[:200]}


def apply_expected(timeline: Any, expected: Mapping[str, Mapping[str, Sequence[Any]]]) -> Dict[str, Any]:
    property_rows = []
    writes = 0
    for name in sorted(expected):
        _track, item = find_item(timeline, name)
        tool = text_tool(item)
        for input_name in sorted(expected[name]):
            series = expected[name][input_name]
            if series_matches(tool, input_name, series):
                property_rows.append({"name": name, "input": input_name, "mutated": False, "write_count": 0, "ok": True})
                continue
            result = write_dense(tool, input_name, series)
            property_rows.append({"name": name, "input": input_name, "mutated": True, **result})
            writes += int(result.get("write_count") or 0)
            if not result.get("ok"):
                return {"ok": False, "property_rows": property_rows, "write_count": writes}
    return {"ok": True, "property_rows": property_rows, "write_count": writes, "mutated_property_count": sum(1 for row in property_rows if row.get("mutated"))}


def verify_authority(authority: Mapping[str, Any]) -> None:
    summary = authority.get("summary") if isinstance(authority.get("summary"), Mapping) else {}
    policy = authority.get("policy") if isinstance(authority.get("policy"), Mapping) else {}
    if authority.get("task_id") != TASK_ID or authority.get("ok") is not True:
        raise ValueError("authority_identity")
    if authority.get("accepted_source_timeline") != SOURCE_TIMELINE_NAME:
        raise ValueError("authority_source")
    if summary.get("physical_textplus") != EXPECTED_TEXTPLUS_COUNT or summary.get("unique_center_target_count") != EXPECTED_CENTER_TARGETS or summary.get("protected_opacity_target_count") != EXPECTED_OPACITY_TARGETS:
        raise ValueError("authority_summary")
    if policy.get("detector_score_controls_opacity") is not False or policy.get("caption_recreation_authorized") is not False or policy.get("size_mutation_authorized") is not False or policy.get("style_mutation_authorized") is not False or policy.get("occlusion_mutation_authorized") is not False:
        raise ValueError("authority_policy")


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
        "center_target_count": EXPECTED_CENTER_TARGETS,
        "opacity_target_count": EXPECTED_OPACITY_TARGETS,
        "targeted_key_write_count": 0,
        "mutated_property_count": 0,
        "caption_recreation_count": 0,
        "size_write_count": 0,
        "style_write_count": 0,
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
        authority = load_json(root / AUTHORITY_RELATIVE_PATH)
        verify_authority(authority)
        authority_hash = hashlib.sha256((root / AUTHORITY_RELATIVE_PATH).read_bytes()).hexdigest()
        config = command.get("motion_fade") if isinstance(command.get("motion_fade"), Mapping) else {}
        if config.get("authority_raw_sha256") != authority_hash:
            raise RuntimeError("authority_hash")

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
        if not source_occ.get("ok") or [source_occ["rows"][0].get("start"), source_occ["rows"][0].get("end")] != EXPECTED_V4_RANGE or source_occ["rows"][0].get("name") != EXPECTED_V4_MATTE:
            raise RuntimeError("source_v4_occlusion")
        source_inventory = V1.stable_inventory(source)
        expected = build_expected(source_snapshot, authority)
        if len(expected) < EXPECTED_OPACITY_TARGETS:
            raise RuntimeError("expected_target_scope")
        base.write_json(report_dir / "motion_fade_preflight.json", {
            "resolve_calls": resolve_calls,
            "source_unique_id": source_uid,
            "source_caption_snapshot_sha256": source_snapshot.get("sha256"),
            "source_v4_occlusion": source_occ,
            "center_targets": sorted(name for name, props in expected.items() if "Center" in props),
            "opacity_targets": sorted(name for name, props in expected.items() if any(prop in props for prop in OPACITY_INPUTS)),
            "frozen_properties": [prop for prop in V1.CAPTION_PROPERTIES if prop not in ALLOWED_PROPERTIES],
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

        base.write_json(report_dir / "motion_fade_application.json", {
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
            "no_caption_recreation": True,
            "no_size_style_or_occlusion_write": True,
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
            "targeted_key_write_count": int(first.get("write_count") or 0),
            "mutated_property_count": int(first.get("mutated_property_count") or 0),
            "persistent_readback_ok": True,
            "idempotency_ok": True,
            "source_timeline_unchanged": True,
            "v4_occlusion_preserved": True,
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
