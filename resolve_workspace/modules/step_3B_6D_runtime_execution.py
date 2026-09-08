"""Contained four-cue Step 3B.6D runtime for the permanent Resolve bridge."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any

TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_RUNTIME_EXECUTION_V1"
VERSION = "step_3B_6D_runtime_execution_v1_0"
PLAN_HASH = "ee6a8fdffbff0f6dc08381ec9180a3bd163aada3bbacf6c6c50d2d6616bdffaf"
EXPECTED = {
    "video_id": "DZsqH7auhjt",
    "project_name": "New Project 1",
    "timeline_name": "DZsqH7auhjt_textplus_full",
    "track_type": "video",
    "track_index": 3,
    "expected_v3_count": 116,
}
TARGETS = {
    "sub_007": {"text": "While", "name": "VC_TEXTPLUS_0007_sub_007", "range": [196, 199], "center": [0.4912565217, 0.5481043478], "size": 0.070191107611},
    "sub_013": {"text": "out", "name": "VC_TEXTPLUS_0013_sub_013", "range": [224, 230], "center": [0.5061210526, 0.5288263158], "size": 0.087909757806},
    "sub_110": {"text": "looks", "name": "VC_TEXTPLUS_0110_sub_110", "range": [862, 868], "center": [0.4991, 0.537], "size": 0.068487834569},
    "sub_114": {"text": "AND", "name": "VC_TEXTPLUS_0114_sub_114", "range": [888, 894], "center": None, "size": None},
}
ARTIFACTS = (
    "accepted_plan_identity_report.json", "preflight_report.json",
    "four_target_pre_state_snapshot.json", "phase_1_mutation_manifest.json",
    "phase_1_persistent_post_state.json", "readback_comparison.json",
    "phase_2_idempotency_report.json", "non_target_mutation_audit.json",
    "protected_inventory_comparison.json", "four_cue_visual_review_checklist.json",
)


def _load_legacy(root: Path) -> Any:
    path = root / "resolve_workspace" / "resolve_apply_caption_source_geometry_contained_rollout_step_3B_6.py"
    previous = os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN")
    os.environ["VC_DISABLE_WORKSPACE_AUTORUN"] = "1"
    try:
        spec = importlib.util.spec_from_file_location("vc_step_3B_6D_legacy_helpers", path)
        if spec is None or spec.loader is None:
            raise ValueError("legacy_runtime_import")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            os.environ.pop("VC_DISABLE_WORKSPACE_AUTORUN", None)
        else:
            os.environ["VC_DISABLE_WORKSPACE_AUTORUN"] = previous


def _json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"not_json_object:{path.name}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path(root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing_path:{label}")
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"outside_repository:{label}") from exc
    return resolved


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _command(command: dict[str, Any], run_id: str) -> tuple[Path, Path, dict[str, Any]]:
    if command.get("task") != TASK_ID or command.get("run_id") != run_id:
        raise ValueError("command_identity")
    if command.get("mode") != "contained_geometry_first_application_and_in_run_idempotency":
        raise ValueError("command_mode")
    payload = command.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("command_payload")
    for key, expected in EXPECTED.items():
        if payload.get(key) != expected:
            raise ValueError(f"identity:{key}")
    if payload.get("allowed_properties") != ["Center", "Size"] or payload.get("forbidden_properties") != ["Blend", "unknown_or_other"]:
        raise ValueError("property_contract")
    root = Path(str(payload.get("repository_root") or "")).resolve()
    if not root.is_dir():
        raise ValueError("repository_root")
    report_dir = _path(root, payload.get("report_dir"), "report_dir")
    plan_path = _path(root, payload.get("plan_path"), "plan_path")
    if report_dir.exists() and any((report_dir / name).exists() for name in ARTIFACTS):
        raise ValueError("conflicting_runtime_artifact")
    return root, plan_path, payload


def _plan(legacy: Any, path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    if _sha(path) != payload.get("plan_file_sha256"):
        raise ValueError("plan_file_hash")
    plan = _json(path)
    if plan.get("plan_hash") != PLAN_HASH or legacy.canonical_hash(plan, ignored=("created_at_unix",)) != PLAN_HASH:
        raise ValueError("plan_semantic_hash")
    failures = legacy.executable_plan_failures(plan)
    if failures:
        raise ValueError("plan_contract:" + ",".join(failures))
    for row in payload.get("prerequisites") or []:
        prerequisite = _path(Path(str(payload["repository_root"])).resolve(), row.get("path"), "prerequisite")
        if not prerequisite.is_file() or _sha(prerequisite) != row.get("sha256"):
            raise ValueError(f"prerequisite_hash:{row.get('path')}")
    return plan


def _target_rows(legacy: Any, tool: Any, targets: list[dict[str, Any]], tolerance: float) -> list[dict[str, Any]]:
    rows = legacy.target_values(tool, targets, tolerance)
    return [{**row, "actual": legacy.json_safe(row.get("actual"))} for row in rows]


def _accepted_static(legacy: Any, cue_id: str, tool: Any, rows: list[dict[str, Any]], tolerance: float) -> bool:
    baseline = TARGETS[cue_id]
    if cue_id == "sub_114" or baseline["center"] is None:
        return False
    if legacy.connected_output(legacy.find_input(tool, "Center")) is not None or legacy.connected_output(legacy.find_input(tool, "Size")) is not None:
        return False
    for row in rows:
        expected = baseline["center"] if row["input"] == "Center" else baseline["size"]
        if not legacy.values_match(row["input"], row.get("actual"), expected, tolerance):
            return False
    return True


def _protected(snapshot: dict[str, Any], target: bool) -> dict[str, Any]:
    if not target:
        return snapshot
    return {key: value for key, value in snapshot.items() if key not in {
        "center_frame_0", "center_modifier_connected", "size_frame_0", "size_modifier_connected"
    }}


def _track_snapshot(legacy: Any, timeline: Any) -> dict[str, Any]:
    return {"tracks": legacy.scan_tracks(timeline), "v3": legacy.v3_ranges({
        legacy.item_name(item): item for item in legacy.track_items(timeline, "video", 3)
    })}


def _timecode(frame: int, fps: float) -> str:
    rounded = int(round(fps))
    if rounded <= 0 or abs(fps - rounded) > 1e-6:
        return f"frame:{frame}"
    frames = int(frame)
    seconds, ff = divmod(frames, rounded)
    minutes, ss = divmod(seconds, 60)
    hours, mm = divmod(minutes, 60)
    return f"{hours:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def _rollback(legacy: Any, manager: Any, acquired: dict[str, Any], snapshots: dict[str, Any], created: list[tuple[str, str]], tolerance: float, settle: float) -> dict[str, Any]:
    result: dict[str, Any] = {"attempted": True, "ok": False, "created_modifiers": [], "static_restoration": [], "persistent_readback": []}
    by_name = {(name, input_name) for name, input_name in created}
    for name, input_name in reversed(created):
        _item, comp, tool = acquired[name]
        legacy.safe_call(comp, "Lock", default=None)
        try:
            returned = legacy.safe_call(tool, "DeleteModifier", input_name, default=False)
            disconnected = legacy.connected_output(legacy.find_input(tool, input_name)) is None
            result["created_modifiers"].append({"name": name, "input": input_name, "returned": legacy.json_safe(returned), "disconnected": disconnected})
        finally:
            legacy.safe_call(comp, "Unlock", default=None)
    for name, values in snapshots.items():
        _item, _comp, tool = acquired[name]
        for input_name in ("Center", "Size"):
            if (name, input_name) not in by_name:
                continue
            expected = values[input_name]
            restored = False
            for variant in legacy.fusion_variants(input_name, expected):
                returned = legacy.safe_call(tool, "SetInput", input_name, variant, default=False)
                if legacy.values_match(input_name, legacy.read_input(tool, input_name, 0), expected, tolerance):
                    restored = True
                    break
            result["static_restoration"].append({"name": name, "input": input_name, "expected": expected, "returned": legacy.json_safe(returned), "restored": restored})
    save_ok = legacy.safe_call(manager, "SaveProject", default=False) is not False
    time.sleep(settle)
    for name, values in snapshots.items():
        _item, _comp, tool = acquired[name]
        for input_name in ("Center", "Size"):
            if (name, input_name) not in by_name:
                continue
            actual = legacy.json_safe(legacy.read_input(tool, input_name, 0))
            topology_ok = legacy.connected_output(legacy.find_input(tool, input_name)) is None
            matched = legacy.values_match(input_name, actual, values[input_name], tolerance)
            result["persistent_readback"].append({"name": name, "input": input_name, "actual": actual, "matched": matched, "topology_ok": topology_ok})
    result["save_ok"] = save_ok
    result["ok"] = bool(save_ok and all(row["disconnected"] for row in result["created_modifiers"]) and all(row["restored"] for row in result["static_restoration"]) and all(row["matched"] and row["topology_ok"] for row in result["persistent_readback"]))
    return result


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    report: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "run_id": run_id, "version": VERSION, "plan_hash": PLAN_HASH, "timeline_modified": False, "setter_call_count": 0, "effective_mutation_count": 0, "blend_operation_count": 0, "failures": []}
    report_dir: Path | None = None
    try:
        root, plan_path, payload = _command(context.get("command") or {}, run_id)
        report_dir = _path(root, payload["report_dir"], "report_dir")
        report_dir.mkdir(parents=True, exist_ok=False) if not report_dir.exists() else None
        legacy = _load_legacy(root)
        plan = _plan(legacy, plan_path, payload)
        tolerance = float(payload.get("value_tolerance") or 1e-5)
        settle = float(payload.get("save_settle_sec") or 1.5)
        _write(report_dir / ARTIFACTS[0], {"ok": True, "task_id": TASK_ID, "run_id": run_id, "path": str(plan_path), "file_sha256": _sha(plan_path), "plan_hash": PLAN_HASH, "cue_ids": list(TARGETS), "operation_counts": {"Center": 18, "Size": 18, "Blend": 0, "other": 0, "total": 36}})

        manager = legacy.safe_call(resolve, "GetProjectManager")
        project = legacy.safe_call(manager, "GetCurrentProject")
        timeline = legacy.safe_call(project, "GetCurrentTimeline")
        if legacy.safe_call(project, "GetName") != EXPECTED["project_name"]:
            raise ValueError("wrong_project")
        if legacy.safe_call(timeline, "GetName") != EXPECTED["timeline_name"]:
            raise ValueError("wrong_timeline")
        before_track = _track_snapshot(legacy, timeline)
        accepted_inventory_report = _json(_path(root, payload.get("accepted_v3_inventory_path"), "accepted_v3_inventory_path"))
        accepted_v3 = ((accepted_inventory_report.get("v3_track_integrity") or {}).get("after") or [])
        if len(accepted_v3) != 116 or before_track["v3"] != accepted_v3:
            raise ValueError("accepted_v3_identity_or_order_drift")
        acquired = legacy.acquire_all(timeline, 116)
        target_names = {row["name"] for row in TARGETS.values()}
        if set(acquired).intersection(target_names) != target_names:
            raise ValueError("target_missing_or_ambiguous")
        all_snapshots = {name: legacy.compact_item_snapshot(item, tool) for name, (item, _comp, tool) in acquired.items()}
        protected_animation_before = legacy.protected_animation_snapshot(acquired, plan.get("protected_animation_targets") or [], tolerance)
        if not all(row.get("present") for row in protected_animation_before):
            raise ValueError("protected_animation_preflight")

        pre_items, rollback_static = [], {}
        plan_by_id = {row["cue_id"]: row for row in plan["rollout_items"]}
        for cue_id, identity in TARGETS.items():
            item_plan = plan_by_id[cue_id]
            item, _comp, tool = acquired[identity["name"]]
            if [legacy.item_start(item), legacy.item_end(item)] != identity["range"] or legacy.normalize_text(legacy.read_input(tool, "StyledText")) != identity["text"]:
                raise ValueError(f"target_identity:{cue_id}")
            rows = _target_rows(legacy, tool, item_plan["targets"], tolerance)
            correct = bool(rows and all(row.get("present") for row in rows))
            static = _accepted_static(legacy, cue_id, tool, rows, tolerance)
            if cue_id == "sub_114" and not correct:
                raise ValueError("sub_114_drift")
            if cue_id != "sub_114" and not (correct or static):
                raise ValueError(f"unexpected_baseline:{cue_id}")
            rollback_static[identity["name"]] = {"Center": legacy.json_safe(legacy.read_input(tool, "Center", 0)), "Size": legacy.json_safe(legacy.read_input(tool, "Size", 0))}
            pre_items.append({"cue_id": cue_id, **identity, "state": "already_correct" if correct else "accepted_static_pre_state", "targets": rows})
        preflight = {"ok": True, "task_id": TASK_ID, "run_id": run_id, "all_targets_validated_before_first_setter": True, "target_count": 4, "non_target_count": 112, "caption_count": 116, "track_snapshot": before_track, "protected_animation": protected_animation_before}
        _write(report_dir / ARTIFACTS[1], preflight)
        _write(report_dir / ARTIFACTS[2], {"ok": True, "task_id": TASK_ID, "run_id": run_id, "items": pre_items})

        setters, created, failures = [], [], []
        for cue_id in TARGETS:
            item_plan = plan_by_id[cue_id]
            name = TARGETS[cue_id]["name"]
            _item, comp, tool = acquired[name]
            mismatches = [row for row in item_plan["targets"] if not legacy.values_match(row["input"], legacy.read_input(tool, row["input"], int(row["local_frame"])), row["expected"], tolerance)]
            for input_name in ("Center", "Size"):
                initially_mismatched = [row for row in mismatches if row["input"] == input_name]
                if not initially_mismatched:
                    continue
                modifier = legacy.ensure_modifier(comp, tool, input_name)
                if modifier.get("created"):
                    created.append((name, input_name))
                if not modifier.get("ok"):
                    failures.append(f"modifier_failed:{cue_id}:{input_name}")
                    break
                for target in (row for row in item_plan["targets"] if row["input"] == input_name):
                    if legacy.values_match(input_name, legacy.read_input(tool, input_name, int(target["local_frame"])), target["expected"], tolerance):
                        continue
                    result = legacy.write_key(tool, input_name, int(target["local_frame"]), target["expected"], tolerance)
                    setters.append({"cue_id": cue_id, "name": name, "input": input_name, "local_frame": int(target["local_frame"]), "timeline_frame": int(target["timeline_frame"]), "expected": target["expected"], "ok": bool(result.get("ok")), "result": result})
                    if not result.get("ok"):
                        failures.append(f"setter_failed:{cue_id}:{input_name}@{target['local_frame']}")
                        break
                if failures:
                    break
            if failures:
                break
        report["setter_call_count"] = len(setters)
        report["effective_mutation_count"] = sum(1 for row in setters if row["ok"])
        report["timeline_modified"] = bool(report["effective_mutation_count"] or created)
        phase1 = {"ok": not failures, "task_id": TASK_ID, "run_id": run_id, "allowed_properties": ["Center", "Size"], "blend_operation_count": 0, "setter_call_count": len(setters), "effective_mutation_count": report["effective_mutation_count"], "created_modifiers": [{"name": name, "input": input_name} for name, input_name in created], "operations": setters, "failures": failures}
        _write(report_dir / ARTIFACTS[3], phase1)
        if failures:
            rollback = _rollback(legacy, manager, acquired, rollback_static, created, tolerance, settle)
            _write(report_dir / "rollback_evidence.json", rollback)
            report["failures"] = failures + (["rollback_failed"] if not rollback["ok"] else ["rollback_required"])
            return report

        save_ok = legacy.safe_call(manager, "SaveProject", default=False) is not False
        if not save_ok:
            failures.append("project_save_failed")
        time.sleep(settle)
        timeline_after = legacy.safe_call(project, "GetCurrentTimeline")
        acquired_after = legacy.acquire_all(timeline_after, 116)
        after_track = _track_snapshot(legacy, timeline_after)
        all_after = {name: legacy.compact_item_snapshot(item, tool) for name, (item, _comp, tool) in acquired_after.items()}
        comparisons = []
        for cue_id in TARGETS:
            item_plan = plan_by_id[cue_id]
            tool = acquired_after[TARGETS[cue_id]["name"]][2]
            for row in _target_rows(legacy, tool, item_plan["targets"], tolerance):
                comparisons.append({"cue_id": cue_id, "name": TARGETS[cue_id]["name"], **row})
        persistent_ok = bool(save_ok and len(comparisons) == 36 and all(row.get("present") for row in comparisons))
        non_target_changes = [name for name in acquired if name not in target_names and not legacy.snapshots_match(all_snapshots[name], all_after.get(name), tolerance)]
        target_protected_changes = [name for name in target_names if not legacy.snapshots_match(_protected(all_snapshots[name], True), _protected(all_after.get(name, {}), True), tolerance)]
        protected_animation_after = legacy.protected_animation_snapshot(acquired_after, plan.get("protected_animation_targets") or [], tolerance)
        integrity_ok = before_track == after_track and not non_target_changes and not target_protected_changes and legacy.snapshots_match(protected_animation_before, protected_animation_after, tolerance)
        _write(report_dir / ARTIFACTS[4], {"ok": persistent_ok, "task_id": TASK_ID, "run_id": run_id, "save_ok": save_ok, "targets": comparisons})
        _write(report_dir / ARTIFACTS[5], {"ok": persistent_ok, "task_id": TASK_ID, "run_id": run_id, "expected_operation_count": 36, "matched_operation_count": sum(1 for row in comparisons if row.get("present")), "Center": 18, "Size": 18, "Blend": 0, "other": 0, "targets": comparisons})
        audit = {"ok": integrity_ok, "task_id": TASK_ID, "run_id": run_id, "non_target_expected": 112, "non_target_changes": non_target_changes, "target_forbidden_changes": target_protected_changes, "track_before": before_track, "track_after": after_track}
        _write(report_dir / ARTIFACTS[7], audit)
        _write(report_dir / ARTIFACTS[8], {"ok": integrity_ok, "task_id": TASK_ID, "run_id": run_id, "protected_animation_before": protected_animation_before, "protected_animation_after": protected_animation_after})
        if not persistent_ok or not integrity_ok:
            rollback = _rollback(legacy, manager, acquired_after, rollback_static, created, tolerance, settle)
            _write(report_dir / "rollback_evidence.json", rollback)
            report["failures"] = (["persistent_readback_failed"] if not persistent_ok else []) + (["protected_state_changed"] if not integrity_ok else []) + (["rollback_failed"] if not rollback["ok"] else ["rollback_required"])
            return report

        phase2 = []
        for cue_id in TARGETS:
            item_plan = plan_by_id[cue_id]
            tool = acquired_after[TARGETS[cue_id]["name"]][2]
            for target in item_plan["targets"]:
                matched = legacy.values_match(target["input"], legacy.read_input(tool, target["input"], int(target["local_frame"])), target["expected"], tolerance)
                phase2.append({"cue_id": cue_id, "input": target["input"], "local_frame": int(target["local_frame"]), "matched": matched, "operation": "compared_and_skipped" if matched else "would_mutate"})
        phase2_ok = len(phase2) == 36 and all(row["matched"] for row in phase2)
        _write(report_dir / ARTIFACTS[6], {"ok": phase2_ok, "task_id": TASK_ID, "run_id": run_id, "same_runtime_boundary": True, "evaluated_operation_count": 36, "setter_call_count": 0, "effective_mutation_count": 0, "blend_operation_count": 0, "timeline_modified": False, "operations": phase2})
        if not phase2_ok:
            rollback = _rollback(legacy, manager, acquired_after, rollback_static, created, tolerance, settle)
            _write(report_dir / "rollback_evidence.json", rollback)
            report["failures"] = ["phase_2_would_mutate", "rollback_failed" if not rollback["ok"] else "rollback_required"]
            return report
        checklist = []
        fps = legacy.finite(legacy.safe_call(project, "GetSetting", "timelineFrameRate", default=24), 24) or 24
        for item in pre_items:
            cue_id = item["cue_id"]
            visibility = plan_by_id[cue_id]["visibility"]
            source_frames = [int(row["source_frame"]) for row in plan_by_id[cue_id]["targets"] if row.get("source_frame") is not None]
            start, end = item["range"]
            checklist.append({"cue_id": cue_id, "text": item["text"], "resolve_item_identity": item["name"], "source_frame_range": [min(source_frames), max(source_frames)], "source_visible_timeline_frame_range": [visibility["source_first_visible_frame"], visibility["source_last_visible_frame"]], "resolve_timeline_frame_range": [start, end], "resolve_timeline_timecode_range": [_timecode(start, fps), _timecode(end, fps)], "center_key_behavior": "dense source-exact planned Center keys", "size_key_behavior": "dense source-exact planned Size keys", "application_state": "already_correct" if item["state"] == "already_correct" else "newly_modified", "expected_visible_motion": "Center and scale follow the accepted source observations", "technical_caveat": "Technical persistence is not visual approval"})
        _write(report_dir / ARTIFACTS[9], {"ok": True, "task_id": TASK_ID, "run_id": run_id, "visual_approval_pending": True, "cues": checklist})
        report.update({"ok": phase2_ok, "timeline_modified": bool(report["effective_mutation_count"]), "persistent_readback_matched": persistent_ok, "non_target_preserved": integrity_ok, "phase_2": {"ok": phase2_ok, "setter_call_count": 0, "effective_mutation_count": 0, "timeline_modified": False}, "manual_visual_approval_required": True})
        return report
    except Exception as exc:
        report["failures"] = [f"{type(exc).__name__}: {exc}"]
        return report
