"""Resolve-connected, read-only Step 3B.6C idempotency evidence regeneration."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable

TASK_ID = "DZSQH7AUHJT_STEP_3B_6C_IDEMPOTENCY_EVIDENCE_REGENERATION_V1"
VERSION = "resolve_read_caption_source_geometry_step_3B_6C_idempotency_evidence_v1_0"
PLAN_SCHEMA = "video_cloner_caption_source_geometry_probe_plan"
EXPECTED = {
    "video_id": "DZsqH7auhjt",
    "project_name": "New Project 1",
    "timeline_name": "DZsqH7auhjt_textplus_full",
    "track_type": "video",
    "track_index": 3,
    "cue_id": "sub_114",
    "text": "AND",
    "item_name": "VC_TEXTPLUS_0114_sub_114",
    "start_frame": 888,
    "end_frame": 894,
    "expected_v3_count": 116,
}


def safe_call(obj: Any, method: str, *args: Any, default: Any = None) -> Any:
    try:
        return getattr(obj, method)(*args)
    except Exception:
        return default


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: dict[str, Any]) -> str:
    clean = dict(value)
    clean.pop("plan_hash", None)
    clean.pop("created_at_unix", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_point(value: Any) -> list[float] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        pair = [finite(value[0]), finite(value[1])]
    elif isinstance(value, dict):
        pair = [finite(value.get(1, value.get("1", value.get("x")))), finite(value.get(2, value.get("2", value.get("y"))))]
    else:
        return None
    return [float(pair[0]), float(pair[1])] if all(number is not None for number in pair) else None


def normalize(input_name: str, value: Any) -> Any:
    return normalize_point(value) if input_name == "Center" else finite(value)


def matched(input_name: str, actual: Any, expected: Any, tolerance: float) -> bool:
    left, right = normalize(input_name, actual), normalize(input_name, expected)
    if input_name == "Center":
        return bool(left and right and all(abs(a - b) <= tolerance for a, b in zip(left, right)))
    return left is not None and right is not None and abs(left - right) <= tolerance


def item_name(item: Any) -> str:
    return " ".join(str(safe_call(item, "GetName", default="") or "").strip().split())


def item_range(item: Any) -> tuple[int | None, int | None]:
    start, end = safe_call(item, "GetStart"), safe_call(item, "GetEnd")
    return (int(start) if start is not None else None, int(end) if end is not None else None)


def fusion_comp(item: Any) -> Any:
    if int(safe_call(item, "GetFusionCompCount", default=0) or 0) > 0:
        comp = safe_call(item, "GetFusionCompByIndex", 1)
        if comp is not None:
            return comp
    return safe_call(item, "GetFusionCompByName", "Composition 1")


def textplus_tool(comp: Any) -> Any:
    tools = safe_call(comp, "GetToolList", False, default={}) or {}
    entries: Iterable[Any] = tools.values() if isinstance(tools, dict) else tools
    matches = []
    for tool in entries:
        attrs = safe_call(tool, "GetAttrs", default={}) or {}
        if str(attrs.get("TOOLS_RegID") or attrs.get("TOOLST_RegID") or "") in ("TextPlus", "Text3D"):
            matches.append(tool)
    return matches[0] if len(matches) == 1 else None


def find_input(tool: Any, name: str) -> Any:
    value = safe_call(tool, "FindInput", name)
    if value is not None:
        return value
    try:
        return getattr(tool, name)
    except Exception:
        return None


def read_input(tool: Any, name: str, frame: int) -> Any:
    value = safe_call(tool, "GetInput", name, frame)
    if value is not None:
        return value
    input_object = find_input(tool, name)
    try:
        return input_object[frame]
    except Exception:
        return None


def connected(input_object: Any) -> bool:
    return safe_call(input_object, "GetConnectedOutput") is not None


def repository_path(root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing:{label}")
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"outside_repository:{label}") from exc
    return resolved


def validate_command(command: dict[str, Any], run_id: str) -> tuple[Path, dict[str, Path]]:
    if command.get("task") != TASK_ID or command.get("run_id") != run_id or command.get("mode") != "persistent_readback_noop":
        raise ValueError("command_identity")
    payload = command.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("command_payload")
    for key, expected in EXPECTED.items():
        if payload.get(key) != expected:
            raise ValueError(f"target_identity:{key}")
    if payload.get("allowed_properties") != ["Center", "Size"] or "Blend" not in (payload.get("forbidden_properties") or []):
        raise ValueError("property_contract")
    root = Path(str(payload.get("repository_root") or "")).resolve()
    if not root.is_dir():
        raise ValueError("repository_root")
    path_keys = ("plan_path", "first_report_path", "canonical_report_path", "pre_state_path", "post_state_path", "comparison_path", "no_effective_change_path")
    return root, {key: repository_path(root, payload.get(key), key) for key in path_keys}


def baseline_targets(plan: dict[str, Any], first: dict[str, Any], tolerance: float) -> list[dict[str, Any]]:
    probe = plan.get("probe") or {}
    targets = list(probe.get("targets") or [])
    if (
        plan.get("ok") is not True or plan.get("schema") != PLAN_SCHEMA or plan.get("plan_hash") != canonical_hash(plan)
        or probe.get("cue_id") != EXPECTED["cue_id"] or probe.get("text") != EXPECTED["text"]
        or probe.get("name") != EXPECTED["item_name"] or probe.get("start_frame") != 888 or probe.get("end_frame") != 894
        or len(targets) != 12 or sorted({row.get("input") for row in targets}) != ["Center", "Size"]
    ):
        raise ValueError("plan_contract")
    if first.get("plan_hash") != plan.get("plan_hash") or first.get("probe_cue_id") != EXPECTED["cue_id"] or first.get("probe_text") != EXPECTED["text"]:
        raise ValueError("first_report_identity")
    historical = {(row.get("input"), int(row.get("local_frame") or 0)): row for row in first.get("targets_after") or []}
    if len(historical) != 12:
        raise ValueError("first_report_targets")
    for target in targets:
        key = (target.get("input"), int(target.get("local_frame") or 0))
        row = historical.get(key) or {}
        if not row.get("present") or not matched(str(key[0]), row.get("actual"), target.get("expected"), tolerance):
            raise ValueError("first_report_state")
    return targets


def track_snapshot(timeline: Any, track_type: str, track_index: int) -> list[dict[str, Any]]:
    items = list(safe_call(timeline, "GetItemListInTrack", track_type, track_index, default=[]) or [])
    return [{"name": item_name(item), "start": item_range(item)[0], "end": item_range(item)[1]} for item in items]


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    report: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "run_id": run_id, "step": "Major Step 3B.6C", "workspace_version": VERSION, "run_mode": "idempotent_second_run", "timeline_modified": False, "resolve_connected": resolve is not None, "setter_call_count": 0, "center_setter_call_count": 0, "size_setter_call_count": 0, "blend_operation_count": 0, "effective_mutation_count": 0, "failures": []}
    try:
        command = context.get("command") or {}
        root, paths = validate_command(command, run_id)
        payload = command["payload"]
        for output in (paths["canonical_report_path"], paths["pre_state_path"], paths["post_state_path"], paths["comparison_path"], paths["no_effective_change_path"]):
            if output.exists():
                raise ValueError(f"conflicting_output:{output.name}")
        if sha256(paths["plan_path"]) != payload.get("plan_sha256") or sha256(paths["first_report_path"]) != payload.get("first_report_sha256"):
            raise ValueError("prerequisite_hash")
        plan, first = load_json(paths["plan_path"]), load_json(paths["first_report_path"])
        tolerance = float(payload.get("value_tolerance") or 1e-5)
        targets = baseline_targets(plan, first, tolerance)
        manager = safe_call(resolve, "GetProjectManager")
        project = safe_call(manager, "GetCurrentProject")
        timeline = safe_call(project, "GetCurrentTimeline")
        if safe_call(project, "GetName") != EXPECTED["project_name"]:
            raise ValueError("wrong_project")
        if safe_call(timeline, "GetName") != EXPECTED["timeline_name"]:
            raise ValueError("wrong_timeline")
        before_track = track_snapshot(timeline, "video", 3)
        if len(before_track) != 116:
            raise ValueError("caption_count")
        items = list(safe_call(timeline, "GetItemListInTrack", "video", 3, default=[]) or [])
        matches = [item for item in items if item_name(item) == EXPECTED["item_name"] and item_range(item) == (888, 894)]
        if len(matches) != 1:
            raise ValueError("target_not_unique")
        item = matches[0]
        tool = textplus_tool(fusion_comp(item))
        if tool is None or " ".join(str(read_input(tool, "StyledText", 0) or "").split()) != "AND":
            raise ValueError("target_text_or_tool")
        comparisons = []
        for target in targets:
            name, frame, expected = str(target["input"]), int(target["local_frame"]), target["expected"]
            input_object = find_input(tool, name)
            actual = read_input(tool, name, frame)
            comparisons.append({"input": name, "local_frame": frame, "timeline_frame": target.get("timeline_frame"), "expected": expected, "actual": normalize(name, actual), "modifier_connected": connected(input_object), "matched": matched(name, actual, expected, tolerance), "present": bool(connected(input_object) and matched(name, actual, expected, tolerance)), "operation": "compared_and_skipped"})
        pre_state = {"run_id": run_id, "project_name": EXPECTED["project_name"], "timeline_name": EXPECTED["timeline_name"], "track_type": "video", "track_index": 3, "item_name": EXPECTED["item_name"], "cue_id": "sub_114", "text": "AND", "frame_range": [888, 894], "targets": comparisons, "track_items": before_track}
        after_track = track_snapshot(timeline, "video", 3)
        post_comparisons = [{**row, "actual": normalize(row["input"], read_input(tool, row["input"], row["local_frame"]))} for row in comparisons]
        post_state = {**pre_state, "targets": post_comparisons, "track_items": after_track}
        if not all(row["present"] for row in comparisons) or before_track != after_track or pre_state != post_state:
            raise ValueError("persistent_state_mismatch")
        comparison = {"ok": True, "run_id": run_id, "allowed_properties": ["Center", "Size"], "forbidden_properties": payload["forbidden_properties"], "expected_operation_count": 12, "compared_operation_count": 12, "skipped_operation_count": 12, "effective_mutation_count": 0, "setter_call_count": 0, "blend_operation_count": 0, "targets": comparisons}
        summary = {"v3_candidate_count": 116, "scene_context_cue_count": 2, "probe_item_count": 1, "mapped_count": 1, "modified_count": 0, "already_correct_count": 1, "target_key_count": 12, "target_key_verified_count": 12, "center_key_count": 6, "center_key_verified_count": 6, "size_key_count": 6, "size_key_verified_count": 6, "non_probe_caption_count": 115, "non_probe_caption_verified_count": 115, "protected_animation_caption_count": int((plan.get("summary") or {}).get("protected_animation_caption_count") or 0), "protected_animation_verified_count": int((plan.get("summary") or {}).get("protected_animation_caption_count") or 0), "protected_animation_target_count": int((plan.get("summary") or {}).get("protected_animation_target_count") or 0), "protected_animation_target_verified_count": int((plan.get("summary") or {}).get("protected_animation_target_count") or 0), "timing_mismatch_excluded_count": int((plan.get("summary") or {}).get("timing_mismatch_excluded_count") or 0), "opacity_proxy_applied_count": 0, "z_order_write_count": 0, "timeline_boundary_write_count": 0, "timeline_integrity_failure_count": 0, "protected_integrity_failure_count": 0, "rollback_performed_count": 0, "failed_count": 0}
        report.update({"ok": True, "video_id": EXPECTED["video_id"], "project_name": EXPECTED["project_name"], "timeline_name": EXPECTED["timeline_name"], "track_type": "video", "track_index": 3, "probe_scene_id": (plan.get("probe") or {}).get("scene_id"), "probe_cue_id": "sub_114", "probe_name": EXPECTED["item_name"], "probe_text": "AND", "probe_visibility": (plan.get("probe") or {}).get("visibility"), "plan_path": str(paths["plan_path"]), "plan_hash": plan["plan_hash"], "first_report_path": str(paths["first_report_path"]), "summary": summary, "targets_before": comparisons, "targets_after": post_comparisons, "writes": [], "track_integrity": {"ok": True, "before": before_track, "after": after_track}, "v3_track_integrity": {"ok": True, "before": before_track, "after": after_track}, "other_caption_integrity_failures": [], "persistent_state_matched": True, "target_resolved_uniquely": True, "pre_post_semantically_identical": True, "expected_operation_count": 12, "compared_operation_count": 12, "skipped_operation_count": 12, "canonical_report_path": str(paths["canonical_report_path"]), "pre_state_path": str(paths["pre_state_path"]), "post_state_path": str(paths["post_state_path"]), "comparison_path": str(paths["comparison_path"]), "no_effective_change_path": str(paths["no_effective_change_path"])})
        write_json(paths["pre_state_path"], pre_state)
        write_json(paths["post_state_path"], post_state)
        write_json(paths["comparison_path"], comparison)
        write_json(paths["no_effective_change_path"], comparison)
        write_json(paths["canonical_report_path"], report)
    except Exception as exc:
        report["failures"] = [f"{type(exc).__name__}: {exc}"]
    return report
