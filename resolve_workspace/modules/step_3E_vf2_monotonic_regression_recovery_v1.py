"""Apply monotonic regression recovery on one isolated Resolve timeline.

The failed Visual Fidelity V2 target is never used as a source. The runtime
duplicates the last visually superior post-metrics baseline and permits only:
- one artifact-driven quarantine removal,
- Center-only correction of 14 source-recovered rows,
- Center-only application of three already-approved protected exits.

All other Text+ properties are captured before mutation and must remain exactly
unchanged before save and after persistent readback.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

TASK_ID = "DZSQH7AUHJT_STEP_3E_VF2_MONOTONIC_REGRESSION_RECOVERY_V1"
MODE = "STEP_3E_VF2_MONOTONIC_REGRESSION_RECOVERY"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_vf2_regression_recovery_v1"
AUTHORITY_RELATIVE_PATH = (
    "artifacts/DZSQH7AUHJT_STEP_3E_VF2_MONOTONIC_REGRESSION_RECOVERY_AUTHORITY_V1/"
    "vf2_monotonic_regression_recovery_authority_v1.json"
)
ACCEPTED_STATE_RELATIVE_PATH = ".agent/state/latest_accepted.json"
EXPECTED_SOURCE_PHYSICAL = 114
EXPECTED_TARGET_PHYSICAL = 113
EXPECTED_STRUCTURAL_SOURCE = 97
EXPECTED_STRUCTURAL_TARGET = 96
EXPECTED_PROTECTED = 17
EXPECTED_CENTER_CORRECTIONS = 14
EXPECTED_PROTECTED_EXITS = 3
EXPECTED_QUARANTINE = 1


def _module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_v2_runtime() -> Any:
    return _module(
        Path(__file__).with_name("step_3E_visual_fidelity_v2_isolated_resolve_rollout_v1.py"),
        "vc_vf2_failed_rollout_helpers_for_monotonic_recovery",
    )


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def same_json(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, separators=(",", ":"), default=str) == json.dumps(
        right, sort_keys=True, separators=(",", ":"), default=str
    )


def authority_partition(authority: Mapping[str, Any]) -> dict[str, Any]:
    if authority.get("task_id") != "DZSQH7AUHJT_STEP_3E_VF2_MONOTONIC_REGRESSION_RECOVERY_AUTHORITY_V1":
        raise ValueError("authority_identity")
    if authority.get("ok") is not True:
        raise ValueError("authority_not_ok")
    summary = authority.get("summary") or {}
    expected = {
        "source_physical_textplus": 114,
        "center_corrections": 14,
        "protected_exit_updates": 3,
        "quarantine_removed": 1,
        "target_physical_textplus": 113,
        "recreated_textplus": 0,
        "size_updates": 0,
        "fill_updates": 0,
        "case_updates": 0,
        "opacity_updates": 0,
        "clip_range_updates": 0,
        "track_updates": 0,
        "occlusion_moves": 0,
    }
    for key, value in expected.items():
        if summary.get(key) != value:
            raise ValueError(f"authority_summary:{key}:{summary.get(key)}")
    policy = authority.get("policy") or {}
    if policy.get("monotonic_non_regression") is not True:
        raise ValueError("monotonic_policy")
    if policy.get("failed_v2_target_may_be_used_as_source") is not False:
        raise ValueError("failed_target_policy")
    for key in (
        "size_mutation_authorized", "fill_mutation_authorized", "case_mutation_authorized",
        "font_mutation_authorized", "opacity_mutation_authorized", "clip_range_mutation_authorized",
        "track_mutation_authorized", "layout_mutation_authorized", "occlusion_relocation_authorized",
    ):
        if policy.get(key) is not False:
            raise ValueError(f"forbidden_mutation_policy:{key}")
    centers = [dict(x) for x in authority.get("center_corrections") or [] if isinstance(x, Mapping)]
    quarantine = [dict(x) for x in authority.get("quarantine_remove") or [] if isinstance(x, Mapping)]
    exits = [dict(x) for x in authority.get("protected_exit_updates") or [] if isinstance(x, Mapping)]
    if (len(centers), len(quarantine), len(exits)) != (14, 1, 3):
        raise ValueError("authority_partition")
    return {
        "centers": centers,
        "quarantine": quarantine,
        "exits": exits,
        "unchanged_structural": list(authority.get("unchanged_structural_target_names") or []),
        "unchanged_protected": list(authority.get("unchanged_protected_target_names") or []),
    }


def capture_text_snapshot(base: Any, old: Any, timeline: Any, name: str) -> dict[str, Any]:
    track, item = base.find_named_item(timeline, name)
    if item is None:
        raise RuntimeError(f"snapshot_missing:{name}")
    summary = base.item_summary(int(track or 0), item)
    duration = int(summary.get("duration") or 0)
    if duration < 1:
        raise RuntimeError(f"snapshot_duration:{name}")
    comp = base.get_comp(item)
    tool = base.get_text_tool(comp)
    if comp is None or tool is None:
        raise RuntimeError(f"snapshot_comp:{name}")
    frames = range(duration)
    return {
        "target_name": name,
        "summary": {k: summary.get(k) for k in (
            "track_index", "start", "end", "duration", "fusion_comp_count", "media_pool_item_name"
        )},
        "static_style": old.capture_static_style(base, item),
        "center": [base.json_safe(base.read_input(tool, "Center", f)) for f in frames],
        "size": [base.json_safe(base.read_input(tool, "Size", f)) for f in range(duration)],
        "opacity1": [base.json_safe(base.read_input(tool, "Opacity1", f)) for f in range(duration)],
        "opacity2": [base.json_safe(base.read_input(tool, "Opacity2", f)) for f in range(duration)],
        "opacity3": [base.json_safe(base.read_input(tool, "Opacity3", f)) for f in range(duration)],
    }


def snapshot_noncenter(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {k: snapshot.get(k) for k in (
        "target_name", "summary", "static_style", "size", "opacity1", "opacity2", "opacity3"
    )}


def point_matches(base: Any, actual: Any, expected: Any, tolerance: float = 0.003) -> bool:
    """Compare Resolve points after normalizing both operands.

    Resolve readback can expose Center as a list-like value while JSON-safe
    snapshots can expose the same point as a keyed mapping.  The legacy shared
    helper normalizes only ``actual`` and therefore raises ``KeyError: 0`` for
    keyed expected values.  Keep the comparison strict, but make malformed point
    shapes a simple mismatch instead of a runtime exception.
    """
    try:
        normalized_actual = base.normalize_point(actual)
        normalized_expected = base.normalize_point(expected)
        if normalized_actual is None or normalized_expected is None:
            return False
        return all(
            abs(float(normalized_actual[index]) - float(normalized_expected[index])) <= float(tolerance)
            for index in (0, 1)
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def verify_static_center(base: Any, item: Any, expected: Sequence[float], tolerance: float = 0.003) -> dict[str, Any]:
    comp = base.get_comp(item)
    tool = base.get_text_tool(comp)
    if comp is None or tool is None:
        return {"ok": False, "error": "comp_or_text_tool"}
    duration = int(base.as_int(base.safe_value(item, "GetEnd", default=0), 0) - base.as_int(base.safe_value(item, "GetStart", default=0), 0))
    if duration < 1:
        # Fall back to item summary if raw calls are unavailable.
        duration = 1
    rows = []
    for frame in range(duration):
        actual = base.read_input(tool, "Center", frame)
        rows.append({"local_frame": frame, "actual": base.json_safe(actual), "matched": point_matches(base, actual, expected, tolerance)})
    return {"rows": rows, "ok": bool(rows and all(x["matched"] for x in rows))}


def apply_center_only(base: Any, old: Any, visual: Any, timeline: Any, row: Mapping[str, Any]) -> dict[str, Any]:
    name = str(row["target_name"])
    track, item = base.find_named_item(timeline, name)
    if item is None:
        return {"target_name": name, "ok": False, "error": "missing"}
    before = capture_text_snapshot(base, old, timeline, name)
    duration = int((before.get("summary") or {}).get("duration") or 0)
    expected = [float(x) for x in row["center_value"]]
    keys = [{"local_frame": frame, "value": expected} for frame in range(duration)]
    comp = base.get_comp(item)
    tool = base.get_text_tool(comp)
    write = visual.apply_center_series(tool, keys) if tool is not None else {"ok": False}
    after = capture_text_snapshot(base, old, timeline, name)
    center_matches = all(point_matches(base, v, expected, 0.003) for v in (after.get("center") or []))
    noncenter_unchanged = same_json(snapshot_noncenter(before), snapshot_noncenter(after))
    return {
        "target_name": name,
        "instance_id": row.get("instance_id"),
        "expected_center": expected,
        "write": write,
        "center_matches": center_matches,
        "noncenter_unchanged": noncenter_unchanged,
        "before": before,
        "after": after,
        "ok": bool(write.get("ok") and center_matches and noncenter_unchanged),
    }


def capture_all(base: Any, old: Any, full: Any, timeline: Any) -> dict[str, dict[str, Any]]:
    names = list(full.source_textplus_names(timeline)) + list(full.visual_first_names(timeline))
    return {name: capture_text_snapshot(base, old, timeline, name) for name in names}


def verify_monotonic(
    base: Any,
    old: Any,
    full: Any,
    timeline: Any,
    source_snapshots: Mapping[str, Mapping[str, Any]],
    authority: Mapping[str, Any],
) -> dict[str, Any]:
    part = authority_partition(authority)
    target_snapshots = capture_all(base, old, full, timeline)
    center_by_name = {str(x["target_name"]): x for x in part["centers"]}
    exit_by_name = {str(x["target_name"]): x for x in part["exits"]}
    quarantine_names = {str(x["target_name"]) for x in part["quarantine"]}

    rows = []
    for name, source in sorted(source_snapshots.items()):
        if name in quarantine_names:
            rows.append({"target_name": name, "kind": "quarantine", "ok": name not in target_snapshots})
            continue
        target = target_snapshots.get(name)
        if target is None:
            rows.append({"target_name": name, "kind": "missing", "ok": False})
            continue
        if name in center_by_name:
            expected = center_by_name[name]["center_value"]
            center_ok = all(point_matches(base, v, expected, 0.003) for v in (target.get("center") or []))
            noncenter_ok = same_json(snapshot_noncenter(source), snapshot_noncenter(target))
            rows.append({"target_name": name, "kind": "center_only", "center_ok": center_ok, "noncenter_ok": noncenter_ok, "ok": center_ok and noncenter_ok})
            continue
        if name in exit_by_name:
            expected_map = {}
            source_summary = source.get("summary") or {}
            start = int(source_summary.get("start") or 0)
            for key in exit_by_name[name].get("position_keys") or []:
                expected_map[int(key["timeline_frame"]) - start] = key["value"]
            center_ok = True
            source_centers = source.get("center") or []
            target_centers = target.get("center") or []
            if len(source_centers) != len(target_centers):
                center_ok = False
            else:
                for frame, actual in enumerate(target_centers):
                    expected = expected_map.get(frame, source_centers[frame])
                    if not point_matches(base, actual, expected, 0.003):
                        center_ok = False
                        break
            noncenter_ok = same_json(snapshot_noncenter(source), snapshot_noncenter(target))
            rows.append({"target_name": name, "kind": "protected_exit_center_only", "center_ok": center_ok, "noncenter_ok": noncenter_ok, "ok": center_ok and noncenter_ok})
            continue
        unchanged = same_json(source, target)
        rows.append({"target_name": name, "kind": "unchanged", "ok": unchanged})

    expected_target_names = set(source_snapshots) - quarantine_names
    unexpected = sorted(set(target_snapshots) - expected_target_names)
    missing = sorted(expected_target_names - set(target_snapshots))
    checks = {
        "row_count": len(rows) == EXPECTED_SOURCE_PHYSICAL,
        "all_rows": all(x.get("ok") for x in rows),
        "no_unexpected_textplus": not unexpected,
        "no_missing_textplus": not missing,
        "physical_count": len(target_snapshots) == EXPECTED_TARGET_PHYSICAL,
    }
    return {"rows": rows, "unexpected": unexpected, "missing": missing, "checks": checks, "ok": all(checks.values())}


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    v2 = load_v2_runtime()
    post = v2.load_post()
    confirmed = post.load_previous()
    old = confirmed.load_old()
    full, pilot, v6, base, media, visual = old.load_runtime()
    root = base.repository_root()
    command = context.get("command") if isinstance(context, dict) else None
    if not isinstance(command, dict):
        raise ValueError("command")
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    if command.get("task_id") != TASK_ID or command.get("mode") != MODE or not run_id:
        raise ValueError("command_identity")
    report_dir = base.relative_path(root, command.get("artifacts_dir"))
    report_dir.mkdir(parents=True, exist_ok=True)
    accepted_path = root / ACCEPTED_STATE_RELATIVE_PATH
    accepted_hash = str(command.get("accepted_state_sha256") or "")
    report = {
        "schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "mode": MODE, "ok": False,
        "source_timeline_name": SOURCE_TIMELINE_NAME, "target_timeline_name": TARGET_TIMELINE_NAME,
        "save_call_count": 0, "center_correction_count": 0, "quarantine_removed_count": 0,
        "protected_exit_update_count": 0, "final_textplus_count": 0, "v2_item_count": 0,
        "monotonic_non_regression": False, "visual_approval_required": True,
        "further_rollout_authorized": False, "failures": [],
    }
    project_manager = project = media_pool = None
    original = source = None
    target_created = False
    original_page = str(base.safe_value(resolve, "GetCurrentPage", default="") or "")
    source_before = []
    source_uid = ""
    try:
        source_contract = base.verify_source_contract(root, command)
        base.write_json(report_dir / "source_contract_verification.json", source_contract)
        if not accepted_path.is_file() or base.raw_sha256(accepted_path) != accepted_hash:
            raise RuntimeError("accepted_state")
        authority = load_json(root / AUTHORITY_RELATIVE_PATH)
        part = authority_partition(authority)

        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        original = base.safe_value(project, "GetCurrentTimeline", default=None)
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        if base.find_timeline(project, TARGET_TIMELINE_NAME) is not None:
            raise RuntimeError("target_exists")

        source_uid = base.timeline_unique_id(source)
        source_before = full.timeline_inventory(source)
        structural = full.source_textplus_names(source)
        protected = full.visual_first_names(source)
        if (len(structural), len(protected), len(structural) + len(protected)) != (
            EXPECTED_STRUCTURAL_SOURCE, EXPECTED_PROTECTED, EXPECTED_SOURCE_PHYSICAL
        ):
            raise RuntimeError("source_physical")
        if full.track_two_item_names(source):
            raise RuntimeError("source_v2")

        source_snapshots = capture_all(base, old, full, source)
        quarantine_names = {str(x["target_name"]) for x in part["quarantine"]}
        center_names = {str(x["target_name"]) for x in part["centers"]}
        exit_names = {str(x["target_name"]) for x in part["exits"]}
        if not quarantine_names <= set(structural):
            raise RuntimeError("quarantine_scope")
        if not center_names <= set(structural):
            raise RuntimeError("center_scope")
        if not exit_names <= set(protected):
            raise RuntimeError("exit_scope")

        occ_name = str((load_json(root / "artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_V2_RESOLVE_ROLLOUT_AUTHORITY_V1/visual_fidelity_v2_resolve_rollout_authority_v1.json").get("occlusion") or {}).get("item_name") or "")
        source_occ = v2.occlusion_inventory(base, source, occ_name) if occ_name else []

        base.write_json(report_dir / "recovery_preflight.json", {
            "resolve_calls": resolve_calls,
            "source_unique_id": source_uid,
            "source_inventory": source_before,
            "source_textplus_snapshot_count": len(source_snapshots),
            "center_scope": sorted(center_names),
            "quarantine_scope": sorted(quarantine_names),
            "protected_exit_scope": sorted(exit_names),
            "source_occlusion": source_occ,
            "authority_semantic_sha256": authority.get("semantic_sha256"),
            "ok": True,
        })

        dup, _ = base.direct_call(source, "DuplicateTimeline", TARGET_TIMELINE_NAME)
        target = dup if dup is not None else base.find_timeline(project, TARGET_TIMELINE_NAME)
        if target is None:
            raise RuntimeError("duplicate_timeline")
        target_created = True
        selected, _ = base.direct_call(project, "SetCurrentTimeline", target)
        if not selected:
            raise RuntimeError("select_target")

        deletion = full.delete_named_textplus(target, sorted(quarantine_names))
        if not deletion.get("ok") or deletion.get("deleted") != EXPECTED_QUARANTINE:
            raise RuntimeError("quarantine_delete")

        center_rows = []
        for row in part["centers"]:
            result = apply_center_only(base, old, visual, target, row)
            center_rows.append(result)
            if not result.get("ok"):
                raise RuntimeError(f"center_only:{row.get('instance_id')}")

        protected_rows = []
        for row in part["exits"]:
            result = v2.apply_protected_exit(base, old, visual, target, row)
            protected_rows.append(result)
            if not result.get("ok"):
                raise RuntimeError(f"protected_exit:{row.get('visual_token_id')}")

        monotonic_before = verify_monotonic(base, old, full, target, source_snapshots, authority)
        if not monotonic_before.get("ok"):
            raise RuntimeError("monotonic_before_save")

        target_occ = v2.occlusion_inventory(base, target, occ_name) if occ_name else []
        if not same_json(source_occ, target_occ):
            raise RuntimeError("occlusion_regression")

        structural_now = full.source_textplus_names(target)
        protected_now = full.visual_first_names(target)
        pre_checks = {
            "center_exact": len(center_rows) == EXPECTED_CENTER_CORRECTIONS and all(x.get("ok") for x in center_rows),
            "quarantine_exact": len(structural_now) == EXPECTED_STRUCTURAL_TARGET and not quarantine_names & set(structural_now),
            "protected_exit_exact": len(protected_rows) == EXPECTED_PROTECTED_EXITS and all(x.get("ok") for x in protected_rows),
            "protected_count": len(protected_now) == EXPECTED_PROTECTED,
            "physical_count": len(structural_now) + len(protected_now) == EXPECTED_TARGET_PHYSICAL,
            "v2_empty": not full.track_two_item_names(target),
            "monotonic_non_regression": monotonic_before.get("ok") is True,
            "occlusion_unchanged": same_json(source_occ, target_occ),
        }
        base.write_json(report_dir / "recovery_readback_before_save.json", {
            "center_rows": center_rows, "protected_exit_rows": protected_rows,
            "monotonic": monotonic_before, "source_occlusion": source_occ, "target_occlusion": target_occ,
            "checks": pre_checks, "ok": all(pre_checks.values()),
        })
        if not all(pre_checks.values()):
            raise RuntimeError("readback_before_save")

        base.direct_call(project, "SetCurrentTimeline", target)
        base.direct_call(resolve, "OpenPage", "edit")
        save = base.save_project(project_manager)
        report["save_call_count"] = 1 if save.get("success") else 0
        if not save.get("success"):
            raise RuntimeError("save")

        project_manager, project, media_pool, reacquire = base.get_project(resolve)
        source_after = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        target_after = base.find_timeline(project, TARGET_TIMELINE_NAME)
        if source_after is None or target_after is None:
            raise RuntimeError("reacquire_timeline")
        source_after_inventory = full.timeline_inventory(source_after)
        monotonic_after = verify_monotonic(base, old, full, target_after, source_snapshots, authority)
        target_occ_after = v2.occlusion_inventory(base, target_after, occ_name) if occ_name else []
        structural_after = full.source_textplus_names(target_after)
        protected_after = full.visual_first_names(target_after)

        persistent_checks = {
            "source_timeline_unchanged": base.timeline_unique_id(source_after) == source_uid and full.stable_inventory(source_after_inventory) == full.stable_inventory(source_before),
            "accepted_state_unchanged": accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash,
            "target_retained": base.timeline_name(target_after) == TARGET_TIMELINE_NAME,
            "monotonic_non_regression": monotonic_after.get("ok") is True,
            "structural_count": len(structural_after) == EXPECTED_STRUCTURAL_TARGET,
            "protected_count": len(protected_after) == EXPECTED_PROTECTED,
            "physical_textplus_count": len(structural_after) + len(protected_after) == EXPECTED_TARGET_PHYSICAL,
            "quarantine_absent": not quarantine_names & set(structural_after),
            "v2_empty": not full.track_two_item_names(target_after),
            "occlusion_unchanged": same_json(source_occ, target_occ_after),
        }
        persistent = {
            "schema_version": 1, "task_id": TASK_ID, "run_id": run_id,
            "monotonic": monotonic_after, "source_occlusion": source_occ, "target_occlusion": target_occ_after,
            "checks": persistent_checks, "save": save, "visual_approval_required": True,
            "further_rollout_authorized": False, "ok": all(persistent_checks.values()),
        }
        base.write_json(report_dir / "persistent_readback.json", persistent)
        if not persistent["ok"]:
            raise RuntimeError("persistent_readback")

        report.update({
            "ok": True,
            "center_correction_count": EXPECTED_CENTER_CORRECTIONS,
            "quarantine_removed_count": EXPECTED_QUARANTINE,
            "protected_exit_update_count": EXPECTED_PROTECTED_EXITS,
            "final_textplus_count": EXPECTED_TARGET_PHYSICAL,
            "v2_item_count": 0,
            "monotonic_non_regression": True,
            "source_timeline_unchanged": True,
            "accepted_state_unchanged": True,
            "target_timeline_kept": True,
            "occlusion_unchanged": True,
            "finished_at": base.utc_now(),
        })
        return report
    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc))
        report["traceback"] = traceback.format_exc()
        if target_created and project_manager is not None and project is not None and media_pool is not None:
            cleanup = v2.cleanup_failure(
                resolve, base, project_manager, project, media_pool, original, original_page,
                accepted_path, accepted_hash
            )
            base.write_json(report_dir / "failure_cleanup.json", cleanup)
            report["failure_cleanup_ok"] = cleanup.get("ok") is True
            report["save_call_count"] = int(cleanup.get("save_call_count") or 0)
        report["finished_at"] = base.utc_now()
        return report
