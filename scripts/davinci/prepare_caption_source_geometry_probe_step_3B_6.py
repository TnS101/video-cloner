#!/usr/bin/env python3
"""Build Major Step 3B.6C source-grounded dense geometry/motion probe plan."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

VERSION = "prepare_caption_source_geometry_probe_step_3B_6C_v1_0_dense_center_size"
SCHEMA = "video_cloner_caption_source_geometry_probe_plan"
SCHEMA_VERSION = "1.0"
EXPECTED_V3_COUNT = 116
DEFAULT_SCENE_ID = "caption_scene_015"


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


def values_close(a: Any, b: Any, tolerance: float = 1e-9) -> bool:
    af = finite(a)
    bf = finite(b)
    return af is not None and bf is not None and abs(af - bf) <= tolerance


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


def scene_by_id(tracks: Dict[str, Any], scene_id: str) -> Optional[Dict[str, Any]]:
    return next((row for row in tracks.get("scenes") or [] if str(row.get("scene_id")) == scene_id), None)


def item_by_cue(animation_plan: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(row.get("cue_id")): row
        for row in (animation_plan.get("items") or [])
        if isinstance(row, dict) and row.get("cue_id")
    }


def observation_frame(row: Dict[str, Any]) -> Optional[int]:
    try:
        return int(row.get("timeline_frame"))
    except (TypeError, ValueError):
        return None


def observation_valid(row: Dict[str, Any]) -> bool:
    frame = observation_frame(row)
    position = row.get("position")
    scale = finite(row.get("scale_proxy"))
    if frame is None or scale is None or scale <= 0:
        return False
    if not isinstance(position, (list, tuple)) or len(position) < 2:
        return False
    x, y = finite(position[0]), finite(position[1])
    return x is not None and y is not None and 0 <= x <= 1 and 0 <= y <= 1


def resolve_center(source_position: Sequence[float]) -> List[float]:
    return [round(float(source_position[0]), 10), round(1.0 - float(source_position[1]), 10)]


def timeline_visibility(track: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    geometry = track.get("geometry") or {}
    first_visible = geometry.get("first_visible_frame")
    last_visible = geometry.get("last_visible_frame")
    start = int(item.get("start_frame") or track.get("cue_start_frame") or 0)
    end = int(item.get("end_frame") or track.get("cue_end_frame") or 0)
    first = int(first_visible) if first_visible is not None else None
    last = int(last_visible) if last_visible is not None else None
    pre = max(0, start - first) if first is not None else None
    post = max(0, last - (end - 1)) if last is not None else None
    late = max(0, first - start) if first is not None else None
    early = max(0, (end - 1) - last) if last is not None else None
    return {
        "timeline_item_start": start,
        "timeline_item_end": end,
        "timeline_item_duration": max(0, end - start),
        "source_first_visible_frame": first,
        "source_last_visible_frame": last,
        "source_visibility_preroll_frames": pre,
        "source_visibility_postroll_frames": post,
        "source_visibility_late_start_frames": late,
        "source_visibility_early_end_frames": early,
        "fully_contained_in_existing_item": bool(first is not None and last is not None and first >= start and last <= end - 1),
    }


def candidate_score(track: Dict[str, Any], visibility: Dict[str, Any]) -> Tuple[int, int, float, float, int]:
    confidence = track.get("confidence") or {}
    return (
        1 if visibility.get("fully_contained_in_existing_item") else 0,
        1 if confidence.get("label") == "high" else 0,
        float(confidence.get("cue_window_coverage") or 0.0),
        float(confidence.get("median_assignment_score") or 0.0),
        int(confidence.get("dense_observation_count") or 0),
    )


def build(args: argparse.Namespace) -> Dict[str, Any]:
    tracks_path = Path(args.tracks).resolve()
    redetection_validation_path = Path(args.redetection_validation).resolve()
    animation_plan_path = Path(args.animation_plan).resolve()
    animation_report_path = Path(args.animation_report).resolve()
    animation_validation_path = Path(args.animation_validation).resolve()
    position_validation_path = Path(args.position_validation).resolve()
    output_path = Path(args.output).resolve()

    tracks = load_json(tracks_path)
    redetection_validation = load_json(redetection_validation_path)
    animation_plan = load_json(animation_plan_path)
    animation_report, animation_report_gate_failures = load_gate(animation_report_path, "step_3C_report", "idempotent_second_run")
    animation_validation, animation_gate_failures = load_gate(animation_validation_path, "step_3C_validation", "idempotent_second_run")
    position_validation, position_gate_failures = load_gate(position_validation_path, "step_3B_5B_validation", "idempotent_second_run")

    failures: List[str] = []
    warnings: List[str] = []
    failures.extend(animation_report_gate_failures)
    failures.extend(animation_gate_failures)
    failures.extend(position_gate_failures)

    if not tracks.get("ok") or tracks.get("schema") != "video_cloner_caption_word_instance_tracks":
        failures.append("tracks_gate_failed")
    if not redetection_validation.get("ok") or redetection_validation.get("failures"):
        failures.append("redetection_validation_gate_failed")
    if int((tracks.get("summary") or {}).get("v3_item_count") or 0) != args.expected_v3_count:
        failures.append("tracks_v3_count_mismatch")
    if int((redetection_validation.get("summary") or {}).get("v3_item_count") or 0) != args.expected_v3_count:
        failures.append("redetection_validation_v3_count_mismatch")
    if int(animation_plan.get("expected_v3_count") or len(animation_plan.get("items") or [])) != args.expected_v3_count:
        failures.append("animation_plan_v3_count_mismatch")
    if not animation_plan.get("ok") or len(animation_plan.get("items") or []) != args.expected_v3_count:
        failures.append("animation_plan_gate_failed")

    tracks_hash = canonical_hash(tracks, ignored=("tracks_hash",))
    declared_tracks_hash = str(tracks.get("tracks_hash") or "")
    if declared_tracks_hash and declared_tracks_hash != tracks_hash:
        # The Step 3B.6B producer includes tracks_hash after calculating the body hash.
        # Recalculate with the same ignored mutable fields; mismatch remains a hard gate.
        failures.append("tracks_hash_mismatch")

    validation_summary = redetection_validation.get("summary") or {}
    preferred_scene_id = str(validation_summary.get("preferred_probe_scene_id") or args.scene_id or DEFAULT_SCENE_ID)
    requested_scene_id = str(args.scene_id or preferred_scene_id)
    if requested_scene_id != preferred_scene_id:
        warnings.append(f"Requested scene {requested_scene_id} differs from validated preferred scene {preferred_scene_id}.")

    scene = scene_by_id(tracks, requested_scene_id)
    if scene is None:
        failures.append(f"probe_scene_not_found:{requested_scene_id}")
        scene = {"scene_id": requested_scene_id, "tracks": []}

    animation_items = item_by_cue(animation_plan)
    scene_context: List[Dict[str, Any]] = []
    candidates: List[Tuple[Tuple[int, int, float, float, int], Dict[str, Any], Dict[str, Any], Dict[str, Any]]] = []

    for track in scene.get("tracks") or []:
        cue_id = str(track.get("cue_id") or "")
        item = animation_items.get(cue_id)
        if item is None:
            failures.append(f"animation_item_missing:{cue_id}")
            continue
        visibility = timeline_visibility(track, item)
        accepted = bool(track.get("accepted_source_instance"))
        confidence = track.get("confidence") or {}
        observations = [row for row in (track.get("frame_observations") or []) if observation_valid(row)]
        in_item = [
            row for row in observations
            if int(item.get("start_frame") or 0) <= int(row["timeline_frame"]) < int(item.get("end_frame") or 0)
        ]
        context = {
            "cue_id": cue_id,
            "name": item.get("name"),
            "text": track.get("text"),
            "style_profile_id": track.get("style_profile_id"),
            "accepted_source_instance": accepted,
            "source_exactness": track.get("source_exactness"),
            "confidence": confidence,
            "visibility": visibility,
            "valid_observation_count": len(observations),
            "in_item_observation_count": len(in_item),
            "apply_eligible": bool(
                accepted
                and confidence.get("label") == "high"
                and visibility.get("fully_contained_in_existing_item")
                and len(in_item) >= 3
                and finite(item.get("base_size"), 0.0) > 0
            ),
            "exclusion_reasons": [],
        }
        if not accepted:
            context["exclusion_reasons"].append("not_accepted_source_instance")
        if confidence.get("label") != "high":
            context["exclusion_reasons"].append("confidence_not_high")
        if not visibility.get("fully_contained_in_existing_item"):
            context["exclusion_reasons"].append("source_visibility_outside_existing_v3_item")
        if len(in_item) < 3:
            context["exclusion_reasons"].append("insufficient_in_item_dense_observations")
        if finite(item.get("base_size"), 0.0) <= 0:
            context["exclusion_reasons"].append("missing_calibrated_base_size")
        scene_context.append(context)
        if context["apply_eligible"]:
            candidates.append((candidate_score(track, visibility), track, item, visibility))

    if not candidates:
        failures.append("no_safe_probe_candidate")
        probe_track = None
        probe_item = None
        probe_visibility = None
    else:
        candidates.sort(key=lambda row: row[0], reverse=True)
        _score, probe_track, probe_item, probe_visibility = candidates[0]

    probe_payload: Dict[str, Any] = {}
    if probe_track is not None and probe_item is not None and probe_visibility is not None:
        cue_id = str(probe_track.get("cue_id"))
        start = int(probe_item.get("start_frame") or 0)
        end = int(probe_item.get("end_frame") or 0)
        duration = end - start
        base_size = float(probe_item.get("base_size"))
        observations = sorted(
            [row for row in (probe_track.get("frame_observations") or []) if observation_valid(row) and start <= int(row["timeline_frame"]) < end],
            key=lambda row: int(row["timeline_frame"]),
        )
        by_frame: Dict[int, Dict[str, Any]] = {}
        for row in observations:
            by_frame[int(row["timeline_frame"])] = row
        expected_frames = list(range(start, end))
        if sorted(by_frame) != expected_frames:
            failures.append(f"probe_dense_frames_not_contiguous:{sorted(by_frame)}")

        center_targets: List[Dict[str, Any]] = []
        size_targets: List[Dict[str, Any]] = []
        opacity_diagnostics: List[Dict[str, Any]] = []
        for timeline_frame in expected_frames:
            row = by_frame.get(timeline_frame)
            if row is None:
                continue
            local_frame = timeline_frame - start
            source_position = [float(row["position"][0]), float(row["position"][1])]
            scale_proxy = float(row["scale_proxy"])
            center_targets.append({
                "input": "Center",
                "local_frame": local_frame,
                "timeline_frame": timeline_frame,
                "expected": resolve_center(source_position),
                "source_position": [round(source_position[0], 10), round(source_position[1], 10)],
                "source_method": row.get("method"),
                "source_frame": row.get("source_frame"),
                "assignment_score": row.get("assignment_score"),
            })
            size_targets.append({
                "input": "Size",
                "local_frame": local_frame,
                "timeline_frame": timeline_frame,
                "expected": round(base_size * scale_proxy, 12),
                "base_size": round(base_size, 12),
                "scale_proxy": round(scale_proxy, 9),
                "source_method": row.get("method"),
                "source_frame": row.get("source_frame"),
                "assignment_score": row.get("assignment_score"),
            })
            opacity_diagnostics.append({
                "local_frame": local_frame,
                "timeline_frame": timeline_frame,
                "opacity_proxy": row.get("opacity_proxy"),
                "raw_opacity_proxy": row.get("raw_opacity_proxy"),
                "applied": False,
                "reason": "contrast-derived proxy is not calibrated source alpha",
            })

        probe_payload = {
            "scene_id": requested_scene_id,
            "cue_id": cue_id,
            "name": probe_item.get("name"),
            "cue_index": probe_track.get("cue_index"),
            "text": probe_track.get("text"),
            "style_profile_id": probe_track.get("style_profile_id"),
            "start_frame": start,
            "end_frame": end,
            "duration_frames": duration,
            "base_size": round(base_size, 12),
            "source_exactness": probe_track.get("source_exactness"),
            "confidence": probe_track.get("confidence"),
            "visibility": probe_visibility,
            "targets": center_targets + size_targets,
            "center_targets": center_targets,
            "size_targets": size_targets,
            "opacity_diagnostics": opacity_diagnostics,
            "write_inputs": ["Center", "Size"],
            "forbidden_writes": ["clip_start", "clip_end", "track_index", "z_order", "Alpha1", "Blend", "outline", "shadow", "fill", "font", "text"],
        }

    protected_animation_targets: List[Dict[str, Any]] = []
    for row in animation_report.get("items") or []:
        targets = []
        for key in row.get("targets") or []:
            input_name = str(key.get("input") or "")
            expected = key.get("expected")
            if input_name not in ("Center", "Size") or expected is None:
                continue
            targets.append({
                "input": input_name,
                "local_frame": int(key.get("local_frame", key.get("frame", 0)) or 0),
                "expected": expected,
            })
        if targets:
            protected_animation_targets.append({
                "cue_id": row.get("cue_id"),
                "name": row.get("name"),
                "animation_type": row.get("animation_type"),
                "targets": targets,
            })

    excluded = [row for row in scene_context if not row.get("apply_eligible")]
    warnings.extend([
        "Step 3B.6C is a one-caption dense Center/Size probe. The other 115 V3 captions are read-only.",
        "Opacity remains diagnostic only because Step 3B.6B emits a contrast proxy, not calibrated source alpha.",
        "Z-order remains diagnostic only and no timeline item is reordered.",
        "Source visibility outside current V3 clip boundaries is reported but not repaired in this step.",
    ])
    for row in excluded:
        vis = row.get("visibility") or {}
        if vis.get("source_visibility_preroll_frames") or vis.get("source_visibility_postroll_frames"):
            warnings.append(
                f"{row.get('cue_id')} / {row.get('text')} is excluded: source visibility extends outside its current V3 item "
                f"(preroll={vis.get('source_visibility_preroll_frames')}, postroll={vis.get('source_visibility_postroll_frames')})."
            )

    payload: Dict[str, Any] = {
        "ok": not failures,
        "step": "Major Step 3B.6C",
        "version": VERSION,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "created_at_unix": time.time(),
        "inputs": {
            "tracks": str(tracks_path),
            "redetection_validation": str(redetection_validation_path),
            "animation_plan": str(animation_plan_path),
            "animation_report": str(animation_report_path),
            "animation_validation": str(animation_validation_path),
            "position_validation": str(position_validation_path),
        },
        "input_hashes": {
            "tracks_declared_hash": declared_tracks_hash,
            "tracks_body_hash": tracks_hash,
            "redetection_validation_hash": redetection_validation.get("validation_hash"),
            "animation_plan_hash": animation_plan.get("plan_hash"),
            "animation_report_plan_hash": animation_report.get("plan_hash"),
            "animation_validation_hash": animation_validation.get("validation_hash"),
            "position_validation_hash": position_validation.get("validation_hash"),
        },
        "expected_v3_count": args.expected_v3_count,
        "selected_scene_id": requested_scene_id,
        "validated_preferred_scene_id": preferred_scene_id,
        "scene_context": scene_context,
        "probe": probe_payload,
        "protected_animation_targets": protected_animation_targets,
        "effect_policy": tracks.get("effect_policy") or {},
        "safety_contract": {
            "one_probe_caption_only": True,
            "timeline_item_boundaries_read_only": True,
            "other_v3_captions_read_only": True,
            "opacity_proxy_diagnostic_only": True,
            "z_order_read_only": True,
            "hard_outline_default_forbidden": True,
            "rollback_on_failure_required": True,
        },
        "summary": {
            "v3_item_count": args.expected_v3_count,
            "scene_context_cue_count": len(scene_context),
            "safe_probe_candidate_count": len(candidates),
            "probe_item_count": 1 if probe_payload else 0,
            "probe_target_count": len(probe_payload.get("targets") or []),
            "center_target_count": len(probe_payload.get("center_targets") or []),
            "size_target_count": len(probe_payload.get("size_targets") or []),
            "opacity_diagnostic_count": len(probe_payload.get("opacity_diagnostics") or []),
            "excluded_scene_context_count": len(excluded),
            "protected_animation_caption_count": len(protected_animation_targets),
            "protected_animation_target_count": sum(len(row.get("targets") or []) for row in protected_animation_targets),
            "timing_mismatch_excluded_count": sum(1 for row in excluded if "source_visibility_outside_existing_v3_item" in (row.get("exclusion_reasons") or [])),
        },
        "warnings": warnings,
        "failures": failures,
    }
    payload["plan_hash"] = canonical_hash(payload, ignored=("created_at_unix",))
    write_json(output_path, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracks", required=True)
    parser.add_argument("--redetection-validation", required=True)
    parser.add_argument("--animation-plan", required=True)
    parser.add_argument("--animation-report", required=True)
    parser.add_argument("--animation-validation", required=True)
    parser.add_argument("--position-validation", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--scene-id", default=DEFAULT_SCENE_ID)
    parser.add_argument("--expected-v3-count", type=int, default=EXPECTED_V3_COUNT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        payload = build(args)
    except Exception as exc:
        payload = {
            "ok": False,
            "step": "Major Step 3B.6C",
            "version": VERSION,
            "failures": ["planner_exception"],
            "exception": f"{type(exc).__name__}: {exc}",
        }
        try:
            write_json(Path(args.output).resolve(), payload)
        except Exception:
            pass
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
