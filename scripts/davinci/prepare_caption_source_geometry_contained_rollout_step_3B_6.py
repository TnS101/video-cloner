#!/usr/bin/env python3
"""Build Major Step 3B.6D contained source-geometry rollout plan."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

VERSION = "prepare_caption_source_geometry_contained_rollout_step_3B_6D_v1_1_center_size_only"
SCHEMA = "video_cloner_caption_source_geometry_contained_rollout_plan"
SCHEMA_VERSION = "1.0"
EXPECTED_V3_COUNT = 116
EXPECTED_TARGET_CUES = ("sub_007", "sub_013", "sub_110", "sub_114")
EXPECTED_TARGET_IDENTITY = {
    "sub_007": ("While", 196, 199),
    "sub_013": ("out", 224, 230),
    "sub_110": ("looks", 862, 868),
    "sub_114": ("AND", 888, 894),
}
ALLOWED_OPERATION_PROPERTIES = ("Center", "Size")
KNOWN_EXCLUDED_SOURCE_PROPERTIES = ("Blend",)
EXPECTED_EXCLUDED_BLEND_BY_CUE = {"sub_007": 2, "sub_013": 2, "sub_110": 2, "sub_114": 0}
ACCEPTED_PROBE_TASK_ID = "DZSQH7AUHJT_STEP_3B_6C_IDEMPOTENCY_EVIDENCE_REGENERATION_V1"
ACCEPTED_PROBE_RUN_ID = "20260802T132415124Z_adb873fd4d154b25a99fd4efce8b6e7f"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp.replace(path)


def canonical_hash(value: Dict[str, Any], ignored: Sequence[str] = ()) -> str:
    clean = dict(value)
    clean.pop("plan_hash", None)
    for key in ignored:
        clean.pop(key, None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def finite(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def select_contained_rollout_operations(
    rows: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    executable: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    unknown: List[str] = []
    for row in rows:
        input_name = str(row.get("input") or "")
        if input_name in ALLOWED_OPERATION_PROPERTIES:
            executable.append(row)
        elif input_name in KNOWN_EXCLUDED_SOURCE_PROPERTIES:
            excluded.append(row)
        else:
            unknown.append(input_name or "<missing>")
    return executable, excluded, sorted(set(unknown))


def load_gate(path: Path, label: str, required_mode: Optional[str] = None) -> Tuple[Dict[str, Any], List[str]]:
    payload = load_json(path)
    failures: List[str] = []
    if not payload.get("ok"):
        failures.append(f"{label}_not_ok")
    if payload.get("failures"):
        failures.append(f"{label}_has_failures")
    if required_mode is not None:
        actual = payload.get("mode", payload.get("run_mode"))
        if actual != required_mode:
            failures.append(f"{label}_wrong_mode:{actual}")
    return payload, failures


def observation_valid(row: Dict[str, Any]) -> bool:
    try:
        int(row.get("timeline_frame"))
    except (TypeError, ValueError):
        return False
    position = row.get("position")
    scale = finite(row.get("scale_proxy"))
    if scale is None or scale <= 0 or not isinstance(position, (list, tuple)) or len(position) < 2:
        return False
    x, y = finite(position[0]), finite(position[1])
    return x is not None and y is not None and 0 <= x <= 1 and 0 <= y <= 1


def resolve_center(source_position: Sequence[float]) -> List[float]:
    return [round(float(source_position[0]), 10), round(1.0 - float(source_position[1]), 10)]


def visibility(track: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    geometry = track.get("geometry") or {}
    first = geometry.get("first_visible_frame")
    last = geometry.get("last_visible_frame")
    first = int(first) if first is not None else None
    last = int(last) if last is not None else None
    start = int(item.get("start_frame") or track.get("cue_start_frame") or 0)
    end = int(item.get("end_frame") or track.get("cue_end_frame") or 0)
    return {
        "timeline_item_start": start,
        "timeline_item_end": end,
        "timeline_item_duration": max(0, end - start),
        "source_first_visible_frame": first,
        "source_last_visible_frame": last,
        "source_visibility_preroll_frames": max(0, start - first) if first is not None else None,
        "source_visibility_postroll_frames": max(0, last - (end - 1)) if last is not None else None,
        "source_visibility_late_start_frames": max(0, first - start) if first is not None else None,
        "source_visibility_early_end_frames": max(0, (end - 1) - last) if last is not None else None,
        "fully_contained_in_existing_item": bool(first is not None and last is not None and first >= start and last <= end - 1),
    }


def build(args: argparse.Namespace) -> Dict[str, Any]:
    paths = {name: Path(getattr(args, name)).resolve() for name in (
        "tracks", "redetection_validation", "animation_plan", "animation_report", "animation_validation",
        "position_validation", "probe_report", "probe_validation", "output"
    )}
    tracks = load_json(paths["tracks"])
    redetection_validation = load_json(paths["redetection_validation"])
    animation_plan = load_json(paths["animation_plan"])
    animation_report, f1 = load_gate(paths["animation_report"], "step_3C_report", "idempotent_second_run")
    _animation_validation, f2 = load_gate(paths["animation_validation"], "step_3C_validation", "idempotent_second_run")
    _position_validation, f3 = load_gate(paths["position_validation"], "step_3B_5B_validation", "idempotent_second_run")
    probe_report, f4 = load_gate(paths["probe_report"], "step_3B_6C_report", "idempotent_second_run")
    probe_validation, f5 = load_gate(paths["probe_validation"], "step_3B_6C_validation", "idempotent_second_run")

    failures: List[str] = [*f1, *f2, *f3, *f4, *f5]
    warnings: List[str] = []
    if not tracks.get("ok") or tracks.get("schema") != "video_cloner_caption_word_instance_tracks":
        failures.append("tracks_gate_failed")
    if not redetection_validation.get("ok") or redetection_validation.get("failures"):
        failures.append("redetection_validation_gate_failed")
    if int((tracks.get("summary") or {}).get("v3_item_count") or 0) != EXPECTED_V3_COUNT:
        failures.append("tracks_v3_count_mismatch")
    if not animation_plan.get("ok") or len(animation_plan.get("items") or []) != EXPECTED_V3_COUNT:
        failures.append("animation_plan_gate_failed")
    if probe_report.get("probe_cue_id") != "sub_114" or int((probe_report.get("summary") or {}).get("target_key_verified_count") or 0) != 12:
        failures.append("step_3B_6C_probe_baseline_not_verified")
    probe_checks = probe_validation.get("checks") if isinstance(probe_validation.get("checks"), dict) else {}
    if not all((
        probe_report.get("task_id") == ACCEPTED_PROBE_TASK_ID,
        probe_report.get("run_id") == ACCEPTED_PROBE_RUN_ID,
        probe_report.get("timeline_modified") is False,
        finite(probe_report.get("setter_call_count"), -1) == 0,
        finite(probe_report.get("effective_mutation_count"), -1) == 0,
        finite(probe_report.get("blend_operation_count"), -1) == 0,
        probe_validation.get("task_id") == ACCEPTED_PROBE_TASK_ID,
        probe_validation.get("run_id") == ACCEPTED_PROBE_RUN_ID,
        bool(probe_checks) and all(value is True for value in probe_checks.values()),
        Path(str(probe_validation.get("report") or "")).resolve() == paths["probe_report"],
    )):
        failures.append("step_3B_6C_canonical_idempotency_evidence_not_verified")

    animation_rows: Dict[str, List[Dict[str, Any]]] = {}
    for row in animation_plan.get("items") or []:
        if row.get("cue_id"):
            animation_rows.setdefault(str(row.get("cue_id")), []).append(row)
    animation_items = {cue_id: rows[0] for cue_id, rows in animation_rows.items()}
    track_rows: Dict[str, List[Dict[str, Any]]] = {}
    track_items: Dict[str, Dict[str, Any]] = {}
    accepted_count = 0
    unresolved_count = 0
    timing_mismatch_count = 0
    for scene in tracks.get("scenes") or []:
        for track in scene.get("tracks") or []:
            cue_id = str(track.get("cue_id") or "")
            track_rows.setdefault(cue_id, []).append(track)
            track_items[cue_id] = track
            if track.get("accepted_source_instance"):
                accepted_count += 1
                item = animation_items.get(cue_id) or {}
                if not visibility(track, item).get("fully_contained_in_existing_item"):
                    timing_mismatch_count += 1
            else:
                unresolved_count += 1

    rollout_items: List[Dict[str, Any]] = []
    for cue_id in EXPECTED_TARGET_CUES:
        if len(track_rows.get(cue_id) or []) != 1:
            failures.append(f"rollout_source_identity_count_failed:{cue_id}:{len(track_rows.get(cue_id) or [])}")
        if len(animation_rows.get(cue_id) or []) != 1:
            failures.append(f"rollout_timeline_identity_count_failed:{cue_id}:{len(animation_rows.get(cue_id) or [])}")
        track = track_items.get(cue_id)
        item = animation_items.get(cue_id)
        if track is None or item is None:
            failures.append(f"rollout_source_missing:{cue_id}")
            continue
        vis = visibility(track, item)
        expected_text, expected_start, expected_end = EXPECTED_TARGET_IDENTITY[cue_id]
        if normalize_text(track.get("text")) != expected_text or normalize_text(item.get("text")) != expected_text:
            failures.append(f"rollout_text_failed:{cue_id}")
        if str(item.get("name") or "") != f"VC_TEXTPLUS_{int(cue_id[-3:]):04d}_{cue_id}":
            failures.append(f"rollout_name_failed:{cue_id}")
        if int(item.get("start_frame") or -1) != expected_start or int(item.get("end_frame") or -1) != expected_end:
            failures.append(f"rollout_timing_failed:{cue_id}")
        if not track.get("accepted_source_instance") or track.get("source_exactness") != "source_redetected_dense_word_instance" or track.get("fallback_reasons"):
            failures.append(f"rollout_cue_not_accepted:{cue_id}")
        if not vis.get("fully_contained_in_existing_item"):
            failures.append(f"rollout_cue_not_contained:{cue_id}")
        start, end = int(item.get("start_frame") or 0), int(item.get("end_frame") or 0)
        base_size = finite(item.get("base_size"), 0.0) or 0.0
        if base_size <= 0:
            failures.append(f"missing_base_size:{cue_id}")
        observations = sorted(
            [row for row in (track.get("frame_observations") or []) if observation_valid(row) and start <= int(row["timeline_frame"]) < end],
            key=lambda row: int(row["timeline_frame"]),
        )
        first, last = vis.get("source_first_visible_frame"), vis.get("source_last_visible_frame")
        expected_visible_frames = list(range(int(first), int(last) + 1)) if first is not None and last is not None else []
        observed_frames = [int(row["timeline_frame"]) for row in observations]
        if observed_frames != expected_visible_frames:
            failures.append(f"dense_visible_frame_contract_failed:{cue_id}:{observed_frames}")

        center_targets: List[Dict[str, Any]] = []
        size_targets: List[Dict[str, Any]] = []
        for row in observations:
            timeline_frame = int(row["timeline_frame"])
            local_frame = timeline_frame - start
            position = [float(row["position"][0]), float(row["position"][1])]
            center_targets.append({
                "input": "Center", "local_frame": local_frame, "timeline_frame": timeline_frame,
                "expected": resolve_center(position), "source_position": position,
                "source_method": row.get("method"), "source_frame": row.get("source_frame"),
                "assignment_score": row.get("assignment_score"),
            })
            scale = float(row["scale_proxy"])
            size_targets.append({
                "input": "Size", "local_frame": local_frame, "timeline_frame": timeline_frame,
                "expected": round(base_size * scale, 12), "base_size": round(base_size, 12),
                "scale_proxy": round(scale, 9), "source_method": row.get("method"),
                "source_frame": row.get("source_frame"), "assignment_score": row.get("assignment_score"),
            })

        excluded_targets: List[Dict[str, Any]] = []
        late = int(vis.get("source_visibility_late_start_frames") or 0)
        early = int(vis.get("source_visibility_early_end_frames") or 0)
        if late > 0:
            excluded_targets.extend([
                {"input": "Blend", "local_frame": 0, "timeline_frame": start, "source_expected": 0.0, "reason": "source_not_yet_visible"},
                {"input": "Blend", "local_frame": late, "timeline_frame": start + late, "source_expected": 1.0, "reason": "source_first_visible_frame"},
            ])
        if early > 0:
            visible_local = int(last) - start
            invisible_local = visible_local + 1
            excluded_targets.extend([
                {"input": "Blend", "local_frame": visible_local, "timeline_frame": int(last), "source_expected": 1.0, "reason": "source_last_visible_frame"},
                {"input": "Blend", "local_frame": invisible_local, "timeline_frame": int(last) + 1, "source_expected": 0.0, "reason": "source_no_longer_visible"},
            ])
        # Preserve the source-derived visibility provenance, but never serialize it as executable geometry.
        unique: Dict[Tuple[str, int], Dict[str, Any]] = {}
        for target in excluded_targets:
            key = (target["input"], int(target["local_frame"]))
            previous = unique.get(key)
            if previous is not None and finite(previous.get("source_expected")) != finite(target.get("source_expected")):
                failures.append(f"conflicting_visibility_target:{cue_id}:{key}")
            unique[key] = target
        excluded_targets = [
            {
                **unique[key],
                "provenance": "source_visibility_boundary",
                "exclusion_reason": "Blend is outside the Step 3B.6D source-geometry property allowlist",
                "executable": False,
            }
            for key in sorted(unique)
        ]
        if len(excluded_targets) != EXPECTED_EXCLUDED_BLEND_BY_CUE[cue_id]:
            failures.append(f"excluded_blend_count_failed:{cue_id}:{len(excluded_targets)}")

        executable_targets, excluded_targets, unknown_properties = select_contained_rollout_operations(
            center_targets + size_targets + excluded_targets
        )
        executable_properties = {str(row.get("input") or "") for row in executable_targets}
        if unknown_properties:
            failures.append(f"unknown_executable_properties:{cue_id}:{unknown_properties}")

        rollout_items.append({
            "scene_id": track.get("scene_id"), "cue_id": cue_id, "cue_index": track.get("cue_index"),
            "name": item.get("name"), "text": track.get("text"), "style_profile_id": track.get("style_profile_id"),
            "start_frame": start, "end_frame": end, "duration_frames": end - start,
            "base_size": round(base_size, 12), "source_exactness": track.get("source_exactness"),
            "accepted_source_instance": bool(track.get("accepted_source_instance")),
            "fallback_reasons": list(track.get("fallback_reasons") or []),
            "confidence": track.get("confidence"), "visibility": vis,
            "targets": executable_targets,
            "center_targets": center_targets, "size_targets": size_targets, "blend_targets": [],
            "excluded_targets": excluded_targets,
            "write_inputs": sorted(executable_properties),
            "forbidden_writes": ["Blend", "clip_start", "clip_end", "track_index", "z_order", "Alpha1", "outline", "shadow", "fill", "font", "text"],
        })

    protected_animation_targets: List[Dict[str, Any]] = []
    for row in animation_report.get("items") or []:
        targets = []
        for target in row.get("targets") or []:
            input_name = str(target.get("input") or "")
            expected = target.get("expected")
            if input_name in ("Center", "Size") and expected is not None:
                targets.append({
                    "input": input_name,
                    "local_frame": int(target.get("local_frame", target.get("frame", 0)) or 0),
                    "expected": expected,
                })
        if targets:
            protected_animation_targets.append({
                "cue_id": row.get("cue_id"), "name": row.get("name"),
                "animation_type": row.get("animation_type"), "targets": targets,
            })

    target_names = {str(row.get("name")) for row in rollout_items}
    if len(target_names) != 4:
        failures.append("rollout_target_name_count_failed")
    if {str(row.get("cue_id")) for row in rollout_items} != set(EXPECTED_TARGET_CUES):
        failures.append("rollout_target_cue_set_failed")

    warnings.extend([
        "Step 3B.6D applies dense Center/Size only to the four accepted cues whose complete source visibility fits inside their existing V3 items.",
        "Six source-derived binary Blend visibility targets are preserved only in the exclusion audit and are not executable.",
        f"{timing_mismatch_count} accepted cues remain excluded because their source visibility extends outside current V3 clip boundaries.",
        f"{unresolved_count} cues remain excluded because Step 3B.6B did not establish source-exact word instances.",
        "Opacity proxies and source visibility boundaries remain diagnostic; no Blend target is written.",
        "Z-order and timeline item boundaries remain read-only.",
    ])

    payload: Dict[str, Any] = {
        "ok": not failures,
        "step": "Major Step 3B.6D",
        "version": VERSION,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "created_at_unix": time.time(),
        "inputs": {name: str(path) for name, path in paths.items() if name != "output"},
        "expected_v3_count": EXPECTED_V3_COUNT,
        "rollout_items": rollout_items,
        "protected_animation_targets": protected_animation_targets,
        "safety_contract": {
            "only_contained_accepted_cues_writable": True,
            "timeline_item_boundaries_read_only": True,
            "other_v3_captions_read_only": True,
            "opacity_proxy_diagnostic_only": True,
            "binary_visibility_gate_allowed": False,
            "center_size_property_allowlist_enforced": True,
            "unknown_properties_fail_closed": True,
            "z_order_read_only": True,
            "hard_outline_default_forbidden": True,
            "solid_outline_100pct_no_blur_forbidden": True,
        },
        "summary": {
            "v3_item_count": EXPECTED_V3_COUNT,
            "accepted_source_instance_count": accepted_count,
            "unresolved_source_instance_count": unresolved_count,
            "timing_mismatch_excluded_count": timing_mismatch_count,
            "rollout_item_count": len(rollout_items),
            "non_rollout_caption_count": EXPECTED_V3_COUNT - len(rollout_items),
            "center_target_count": sum(len(row["center_targets"]) for row in rollout_items),
            "size_target_count": sum(len(row["size_targets"]) for row in rollout_items),
            "blend_target_count": sum(len(row["blend_targets"]) for row in rollout_items),
            "other_property_target_count": sum(
                1 for row in rollout_items for target in row["targets"]
                if str(target.get("input") or "") not in ALLOWED_OPERATION_PROPERTIES
            ),
            "excluded_blend_target_count": sum(len(row["excluded_targets"]) for row in rollout_items),
            "total_target_count": sum(len(row["targets"]) for row in rollout_items),
            "visibility_gated_caption_count": 0,
            "visibility_exclusion_audit_caption_count": sum(1 for row in rollout_items if row["excluded_targets"]),
            "expected_first_modified_count": 3,
            "expected_first_already_correct_count": 1,
            "protected_animation_caption_count": len(protected_animation_targets),
            "protected_animation_target_count": sum(len(row["targets"]) for row in protected_animation_targets),
        },
        "property_contract": {
            "allowed_operation_properties": list(ALLOWED_OPERATION_PROPERTIES),
            "known_excluded_source_properties": list(KNOWN_EXCLUDED_SOURCE_PROPERTIES),
            "unknown_properties_fail_closed": True,
        },
        "warnings": warnings,
        "failures": failures,
    }
    payload["plan_hash"] = canonical_hash(payload, ignored=("created_at_unix",))
    write_json(paths["output"], payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracks", required=True)
    parser.add_argument("--redetection-validation", required=True)
    parser.add_argument("--animation-plan", required=True)
    parser.add_argument("--animation-report", required=True)
    parser.add_argument("--animation-validation", required=True)
    parser.add_argument("--position-validation", required=True)
    parser.add_argument("--probe-report", required=True)
    parser.add_argument("--probe-validation", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        payload = build(args)
    except Exception as exc:
        payload = {"ok": False, "step": "Major Step 3B.6D", "version": VERSION, "failures": ["planner_exception"], "exception": f"{type(exc).__name__}: {exc}"}
        write_json(Path(args.output).resolve(), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
