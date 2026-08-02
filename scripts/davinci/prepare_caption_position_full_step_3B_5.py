#!/usr/bin/env python3
"""Build Major Step 3B.5B full V3 source-position rollout plan.

Direct source anchors are preferred. Cues without direct events use a strict
near-time classified group, temporal interpolation, or nearest direct event.
Existing Step 3C slide animations are translated to the new source position
without changing their relative motion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

VERSION = "prepare_caption_position_step_3B_5B_v1_0_full_source_position_rollout"
EXPECTED_V3_COUNT = 116
ACCEPTED_PROBE_CUE_ID = "sub_034"
GROUP_TIME_TOLERANCE_SEC = 0.35
INTERPOLATION_MAX_GAP_SEC = 2.0


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


def canonical_hash(value: Dict[str, Any]) -> str:
    clean = dict(value)
    clean.pop("plan_hash", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def finite(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def normalize_point(value: Any) -> Optional[List[float]]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        x, y = finite(value[0]), finite(value[1])
        if x is not None and y is not None:
            return [x, y]
    if isinstance(value, dict):
        x = value.get(1, value.get("1", value.get("x", value.get("X"))))
        y = value.get(2, value.get("2", value.get("y", value.get("Y"))))
        x, y = finite(x), finite(y)
        if x is not None and y is not None:
            return [x, y]
    return None


def validate_gate(payload: Dict[str, Any], label: str, mode: str) -> List[str]:
    failures: List[str] = []
    if not payload.get("ok"):
        failures.append(f"{label}_not_ok")
    actual_mode = payload.get("mode", payload.get("run_mode"))
    if actual_mode != mode:
        failures.append(f"{label}_wrong_mode:{actual_mode}")
    if payload.get("failures"):
        failures.append(f"{label}_has_failures")
    return failures


def source_anchor(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    resolution = row.get("profile_resolution") or {}
    details = resolution.get("details") or {}
    event = details.get("event") if isinstance(details, dict) else None
    if isinstance(event, dict):
        placement = event.get("placement") or {}
        anchor = placement.get("anchor") or {}
        x, y = finite(anchor.get("x")), finite(anchor.get("y"))
        if x is not None and y is not None:
            return {
                "source": "caption_style_event.placement.anchor",
                "source_detail_id": event.get("event_id"),
                "source_time": finite(event.get("mid"), finite(event.get("start"))),
                "source_point": [x, y],
                "confidence_score": (event.get("confidence") or {}).get("score"),
                "confidence_label": (event.get("confidence") or {}).get("label"),
            }
    return None


def group_candidate(row: Dict[str, Any], midpoint_seconds: float) -> Optional[Dict[str, Any]]:
    resolution = row.get("profile_resolution") or {}
    details = resolution.get("details") or {}
    group = details.get("group") if isinstance(details, dict) else None
    if not isinstance(group, dict):
        return None
    point = normalize_point(group.get("center"))
    timestamp = finite(group.get("timestamp"))
    matched = {str(value) for value in (group.get("matched_cue_ids") or [])}
    cue_id = str(row.get("cue_id") or "")
    cue_index = int(row.get("cue_index") or row.get("cue_number") or 0)
    cue_tokens = {cue_id, str(cue_index), f"sub_{cue_index:04d}", f"sub_{cue_index:03d}"}
    is_matched = bool(matched.intersection(cue_tokens)) if matched else True
    if point is None or timestamp is None or not is_matched:
        return None
    delta = abs(timestamp - midpoint_seconds)
    if delta > GROUP_TIME_TOLERANCE_SEC:
        return None
    return {
        "source": "classified_caption_group.center_near_cue_time",
        "source_detail_id": group.get("frame_index"),
        "source_time": timestamp,
        "source_time_delta_sec": round(delta, 6),
        "source_point": point,
        "confidence_score": resolution.get("confidence", group.get("confidence")),
        "confidence_label": "near_time_classified_group",
    }


def current_center(row: Dict[str, Any]) -> Optional[List[float]]:
    preserved = row.get("preserved_inputs_after") or row.get("preserved_inputs_before") or {}
    center = preserved.get("Center") or {}
    return normalize_point(center.get("value") if isinstance(center, dict) else center)


def resolve_center_from_source(point: List[float]) -> List[float]:
    return [round(float(point[0]), 10), round(1.0 - float(point[1]), 10)]


def build(args: argparse.Namespace) -> Dict[str, Any]:
    font_path = Path(args.font_report).resolve()
    step3c_path = Path(args.step_3c_report).resolve()
    fill_report_path = Path(args.step_3b4b_idempotency_report).resolve()
    fill_validation_path = Path(args.step_3b4b_idempotency_validation).resolve()
    probe_report_path = Path(args.step_3b5a_idempotency_report).resolve()
    probe_validation_path = Path(args.step_3b5a_idempotency_validation).resolve()

    font = load_json(font_path)
    step3c = load_json(step3c_path)
    fill_report = load_json(fill_report_path)
    fill_validation = load_json(fill_validation_path)
    probe_report = load_json(probe_report_path)
    probe_validation = load_json(probe_validation_path)

    failures: List[str] = []
    warnings: List[str] = [
        "This is the full 116-caption position rollout. Use a duplicate of the accepted Step 3B.5A timeline.",
        "Direct event anchors are strongest. 50 captions use bounded inferred positions: 33 near-time groups, 16 temporal interpolations, and 1 nearest-event fallback.",
        "Four Step 3C slide animations are translated as complete Center-keyframe pairs so their relative motion is preserved.",
    ]

    if not font.get("ok") or int(font.get("v3_candidate_count") or 0) != args.expected_v3_count:
        failures.append("font_report_gate_failed")
    failures.extend(validate_gate(step3c, "step_3C", "idempotent_second_run"))
    failures.extend(validate_gate(fill_report, "step_3B_4B_report", "idempotent_second_run"))
    failures.extend(validate_gate(fill_validation, "step_3B_4B_validation", "idempotent_second_run"))
    failures.extend(validate_gate(probe_report, "step_3B_5A_report", "idempotent_second_run"))
    failures.extend(validate_gate(probe_validation, "step_3B_5A_validation", "idempotent_second_run"))

    fill_summary = fill_report.get("summary") or {}
    if int(fill_summary.get("fill_verified_count") or 0) != args.expected_v3_count:
        failures.append("step_3B_4B_fill_integrity")
    if int(fill_summary.get("protected_effect_verified_count") or 0) != args.expected_v3_count:
        failures.append("step_3B_4B_effect_integrity")
    if int(fill_summary.get("protected_animation_verified_count") or 0) != 16:
        failures.append("step_3B_4B_animation_integrity")

    probe_summary = probe_report.get("summary") or {}
    if int(probe_summary.get("position_verified_count") or 0) != 1:
        failures.append("step_3B_5A_position_integrity")
    if int(probe_summary.get("protected_animation_verified_count") or 0) != 16:
        failures.append("step_3B_5A_animation_integrity")

    rows: List[Dict[str, Any]] = []
    direct_rows: List[Dict[str, Any]] = []
    for raw in font.get("items") or []:
        if not isinstance(raw, dict):
            failures.append("non_object_font_item")
            continue
        start = int(raw.get("start") or 0)
        end = int(raw.get("end") or 0)
        midpoint = ((start + end) / 2.0) / 24.0
        direct = source_anchor(raw)
        row = {
            "raw": raw,
            "cue_id": str(raw.get("cue_id") or ""),
            "name": str(raw.get("name") or ""),
            "cue_index": int(raw.get("cue_index") or raw.get("cue_number") or 0),
            "midpoint_seconds": midpoint,
            "style_profile_id": str((raw.get("profile_resolution") or {}).get("style_profile_id") or ""),
            "direct": direct,
        }
        rows.append(row)
        if direct:
            direct_rows.append(row)

    if len(rows) != args.expected_v3_count:
        failures.append(f"font_item_count_mismatch:{len(rows)}")
    if len(direct_rows) != 66:
        failures.append(f"direct_event_position_count_mismatch:{len(direct_rows)}")

    profile_medians: Dict[str, List[float]] = {}
    for profile in sorted({row["style_profile_id"] for row in direct_rows}):
        points = [row["direct"]["source_point"] for row in direct_rows if row["style_profile_id"] == profile]
        if points:
            profile_medians[profile] = [statistics.median(p[0] for p in points), statistics.median(p[1] for p in points)]

    step3c_items = {str(row.get("cue_id")): row for row in (step3c.get("items") or []) if isinstance(row, dict) and row.get("cue_id")}
    plan_items: List[Dict[str, Any]] = []
    source_counts: Dict[str, int] = {}
    seen_names: set[str] = set()
    seen_cues: set[str] = set()
    animated_center_caption_count = 0
    shifted_center_keyframe_count = 0

    for row in rows:
        raw = row["raw"]
        name, cue_id = row["name"], row["cue_id"]
        if not name or not cue_id or name in seen_names or cue_id in seen_cues:
            failures.append(f"invalid_or_duplicate_item:{name}:{cue_id}")
            continue
        seen_names.add(name)
        seen_cues.add(cue_id)

        source = row["direct"]
        if source is None:
            source = group_candidate(raw, row["midpoint_seconds"])
        if source is None:
            previous = [candidate for candidate in direct_rows if candidate["midpoint_seconds"] <= row["midpoint_seconds"]]
            following = [candidate for candidate in direct_rows if candidate["midpoint_seconds"] >= row["midpoint_seconds"]]
            left = max(previous, key=lambda candidate: candidate["midpoint_seconds"]) if previous else None
            right = min(following, key=lambda candidate: candidate["midpoint_seconds"]) if following else None
            if (left and right and right["midpoint_seconds"] > left["midpoint_seconds"]
                    and row["midpoint_seconds"] - left["midpoint_seconds"] <= INTERPOLATION_MAX_GAP_SEC
                    and right["midpoint_seconds"] - row["midpoint_seconds"] <= INTERPOLATION_MAX_GAP_SEC):
                fraction = (row["midpoint_seconds"] - left["midpoint_seconds"]) / (right["midpoint_seconds"] - left["midpoint_seconds"])
                lp, rp = left["direct"]["source_point"], right["direct"]["source_point"]
                point = [lp[0] + (rp[0] - lp[0]) * fraction, lp[1] + (rp[1] - lp[1]) * fraction]
                source = {
                    "source": "interpolated_between_direct_event_anchors",
                    "source_detail_id": [left["cue_id"], right["cue_id"]],
                    "source_time": row["midpoint_seconds"],
                    "source_point": point,
                    "confidence_score": min(finite(left["direct"].get("confidence_score"), 0.0) or 0.0, finite(right["direct"].get("confidence_score"), 0.0) or 0.0),
                    "confidence_label": "temporal_interpolation",
                    "interpolation_fraction": round(fraction, 8),
                }
            else:
                nearest = min(direct_rows, key=lambda candidate: abs(candidate["midpoint_seconds"] - row["midpoint_seconds"])) if direct_rows else None
                if nearest and abs(nearest["midpoint_seconds"] - row["midpoint_seconds"]) <= INTERPOLATION_MAX_GAP_SEC:
                    source = {
                        "source": "nearest_direct_event_anchor",
                        "source_detail_id": nearest["cue_id"],
                        "source_time": nearest["midpoint_seconds"],
                        "source_time_delta_sec": round(abs(nearest["midpoint_seconds"] - row["midpoint_seconds"]), 6),
                        "source_point": list(nearest["direct"]["source_point"]),
                        "confidence_score": nearest["direct"].get("confidence_score"),
                        "confidence_label": "nearest_temporal_direct_event",
                    }
                else:
                    median = profile_medians.get(row["style_profile_id"])
                    if median is None:
                        failures.append(f"no_position_source:{name}")
                        continue
                    source = {
                        "source": "style_profile_direct_event_median",
                        "source_detail_id": row["style_profile_id"],
                        "source_time": row["midpoint_seconds"],
                        "source_point": list(median),
                        "confidence_score": None,
                        "confidence_label": "profile_median_fallback",
                    }

        source_counts[source["source"]] = source_counts.get(source["source"], 0) + 1
        target_center = resolve_center_from_source(source["source_point"])

        protected_animation_targets: List[Dict[str, Any]] = []
        for target in (step3c_items.get(cue_id) or {}).get("targets") or []:
            if isinstance(target, dict):
                protected_animation_targets.append({
                    "input": str(target.get("input") or ""),
                    "local_frame": int(target.get("local_frame") or 0),
                    "expected": target.get("expected"),
                })

        center_targets = [target for target in protected_animation_targets if target.get("input") == "Center"]
        target_animation_targets: List[Dict[str, Any]] = []
        center_delta: Optional[List[float]] = None
        write_mode = "static_center"
        if center_targets:
            sorted_center_targets = sorted(center_targets, key=lambda target: int(target.get("local_frame") or 0))
            old_final = normalize_point(sorted_center_targets[-1].get("expected"))
            if old_final is None:
                failures.append(f"invalid_center_animation_target:{name}")
                continue
            center_delta = [round(target_center[0] - old_final[0], 10), round(target_center[1] - old_final[1], 10)]
            write_mode = "translated_center_animation"
            animated_center_caption_count += 1
            shifted_center_keyframe_count += len(sorted_center_targets)

        for target in protected_animation_targets:
            expected = target.get("expected")
            if target.get("input") == "Center" and center_delta is not None:
                point = normalize_point(expected)
                if point is None:
                    failures.append(f"invalid_center_animation_point:{name}:{target.get('local_frame')}")
                    continue
                expected = [round(point[0] + center_delta[0], 10), round(point[1] + center_delta[1], 10)]
            target_animation_targets.append({
                "input": target.get("input"),
                "local_frame": int(target.get("local_frame") or 0),
                "expected": expected,
            })

        plan_items.append({
            "name": name,
            "cue_id": cue_id,
            "cue_index": row["cue_index"],
            "start": int(raw.get("start") or 0),
            "end": int(raw.get("end") or 0),
            "text": str(raw.get("rendered_text") or ""),
            "expected_font_family": str(raw.get("font_after") or raw.get("requested_family") or ""),
            "expected_font_face": str(raw.get("style_after") or raw.get("requested_face") or ""),
            "style_profile_id": row["style_profile_id"],
            "rollout_target": True,
            "accepted_probe": cue_id == ACCEPTED_PROBE_CUE_ID,
            "source_position": source,
            "target_center": target_center,
            "previous_reported_center": current_center(raw),
            "position_write_mode": write_mode,
            "center_animation_delta": center_delta,
            "protected_animation_targets_before": protected_animation_targets,
            "expected_animation_targets_after": target_animation_targets,
        })

    plan_items.sort(key=lambda item: (item["cue_index"], item["name"]))
    accepted_probes = [item for item in plan_items if item["accepted_probe"]]
    animation_target_count = sum(len(item["protected_animation_targets_before"]) for item in plan_items)
    expected_animation_target_count = sum(len(item["expected_animation_targets_after"]) for item in plan_items)

    if len(plan_items) != args.expected_v3_count:
        failures.append(f"plan_item_count_mismatch:{len(plan_items)}")
    if len(accepted_probes) != 1:
        failures.append(f"accepted_probe_count_mismatch:{len(accepted_probes)}")
    if animation_target_count != 16 or expected_animation_target_count != 16:
        failures.append(f"animation_target_count_mismatch:{animation_target_count}:{expected_animation_target_count}")
    if animated_center_caption_count != 4 or shifted_center_keyframe_count != 8:
        failures.append(f"center_animation_translation_count_mismatch:{animated_center_caption_count}:{shifted_center_keyframe_count}")

    expected_source_counts = {
        "caption_style_event.placement.anchor": 66,
        "classified_caption_group.center_near_cue_time": 33,
        "interpolated_between_direct_event_anchors": 16,
        "nearest_direct_event_anchor": 1,
    }
    for key, expected in expected_source_counts.items():
        if source_counts.get(key, 0) != expected:
            failures.append(f"position_source_count_mismatch:{key}:{source_counts.get(key, 0)}:{expected}")

    accepted = accepted_probes[0] if accepted_probes else None
    if accepted:
        if accepted.get("target_center") != [0.3833, 0.6724]:
            failures.append(f"unexpected_accepted_probe_target:{accepted.get('target_center')}")
        if accepted.get("source_position", {}).get("source") != "classified_caption_group.center_near_cue_time":
            failures.append("unexpected_accepted_probe_source_method")
        if accepted.get("position_write_mode") != "static_center":
            failures.append("accepted_probe_must_be_static_center")

    plan: Dict[str, Any] = {
        "ok": not failures,
        "schema": "video_cloner_caption_position_full_rollout_plan",
        "schema_version": "1.0",
        "step": "Major Step 3B.5B",
        "planner_version": VERSION,
        "created_at_unix": round(time.time(), 6),
        "expected_v3_count": args.expected_v3_count,
        "timeline_fps": 24.0,
        "accepted_probe_cue_id": ACCEPTED_PROBE_CUE_ID,
        "position_policy": {
            "coordinate_conversion": "Resolve Text+ Center = [source_x, 1 - source_y]",
            "priority": [
                "caption_style_event.placement.anchor",
                "classified_caption_group.center_near_cue_time",
                "interpolated_between_direct_event_anchors",
                "nearest_direct_event_anchor",
                "style_profile_direct_event_median",
            ],
            "group_time_tolerance_sec": GROUP_TIME_TOLERANCE_SEC,
            "interpolation_max_gap_sec": INTERPOLATION_MAX_GAP_SEC,
            "slide_animation_policy": "translate all existing Center keyframes by target_center minus previous final Center keyframe",
        },
        "inputs": {
            "font_report": str(font_path),
            "step_3c_idempotency_report": str(step3c_path),
            "step_3b4b_idempotency_report": str(fill_report_path),
            "step_3b4b_idempotency_validation": str(fill_validation_path),
            "step_3b5a_idempotency_report": str(probe_report_path),
            "step_3b5a_idempotency_validation": str(probe_validation_path),
        },
        "summary": {
            "v3_item_count": len(plan_items),
            "rollout_target_count": len(plan_items),
            "accepted_probe_count": len(accepted_probes),
            "direct_event_position_count": source_counts.get("caption_style_event.placement.anchor", 0),
            "near_group_position_count": source_counts.get("classified_caption_group.center_near_cue_time", 0),
            "interpolated_position_count": source_counts.get("interpolated_between_direct_event_anchors", 0),
            "nearest_event_position_count": source_counts.get("nearest_direct_event_anchor", 0),
            "profile_median_position_count": source_counts.get("style_profile_direct_event_median", 0),
            "static_center_caption_count": len(plan_items) - animated_center_caption_count,
            "translated_center_animation_caption_count": animated_center_caption_count,
            "translated_center_keyframe_count": shifted_center_keyframe_count,
            "animation_target_count_before": animation_target_count,
            "animation_target_count_after": expected_animation_target_count,
        },
        "items": plan_items,
        "warnings": warnings,
        "failures": failures,
    }
    plan["plan_hash"] = canonical_hash(plan)
    write_json(Path(args.output).resolve(), plan)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--font-report", required=True)
    parser.add_argument("--step-3c-report", required=True)
    parser.add_argument("--step-3b4b-idempotency-report", required=True)
    parser.add_argument("--step-3b4b-idempotency-validation", required=True)
    parser.add_argument("--step-3b5a-idempotency-report", required=True)
    parser.add_argument("--step-3b5a-idempotency-validation", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-v3-count", type=int, default=EXPECTED_V3_COUNT)
    args = parser.parse_args()
    try:
        plan = build(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "exception": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 1
    print(json.dumps({
        "ok": plan.get("ok"), "step": plan.get("step"), "planner_version": plan.get("planner_version"),
        "summary": plan.get("summary"), "warnings": plan.get("warnings"), "failures": plan.get("failures"),
        "output": str(Path(args.output).resolve()),
    }, indent=2))
    return 0 if plan.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
