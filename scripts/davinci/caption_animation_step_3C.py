#!/usr/bin/env python3
"""
Video Cloner — Major Step 3C
Source-faithful caption-animation planning and validation.

Commands:

    prepare
        Reads the merged analysis and the successful Step 3B.2 size plan/report.
        Produces a strict animation plan for the existing 116 V3 Text+ clips.

    validate
        Validates either the first Resolve application or the second-run
        idempotency report.

This script intentionally does not fabricate animation for static captions.
Only detected, normalized and structurally safe source events are selected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


VERSION = "caption_animation_step_3C_v1_0_source_relative_time_clone"
SCHEMA = "video_cloner_caption_animation_plan"
SUPPORTED_TYPES = {"scale", "slide", "scale_pop"}

MIN_CONFIDENCE = {
    "scale": 0.52,
    "slide": 0.62,
    "scale_pop": 0.78,
}


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: str, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    temp = target.with_suffix(target.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    temp.replace(target)


def file_sha256(path: str) -> Optional[str]:
    target = Path(path)
    if not target.is_file():
        return None

    digest = hashlib.sha256()
    with open(target, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def as_float(value: Any) -> Optional[float]:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> Optional[int]:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def point_from_value(value: Any) -> Optional[Tuple[float, float]]:
    if isinstance(value, dict):
        x = value.get("x", value.get("X", value.get(1, value.get("1"))))
        y = value.get("y", value.get("Y", value.get(2, value.get("2"))))
        x_value = as_float(x)
        y_value = as_float(y)
        if x_value is not None and y_value is not None:
            return x_value, y_value

    if isinstance(value, (list, tuple)) and len(value) >= 2:
        x_value = as_float(value[0])
        y_value = as_float(value[1])
        if x_value is not None and y_value is not None:
            return x_value, y_value

    return None


def iter_nodes(root: Any) -> Iterable[Any]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node

        if isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def cue_number(cue_id: str) -> int:
    match = re.search(r"(\d+)$", str(cue_id or ""))
    return int(match.group(1)) if match else 10**9


def event_quality(event: Dict[str, Any]) -> Tuple[float, int, int]:
    animation = event.get("animation") or {}
    confidence = as_float(animation.get("confidence")) or 0.0
    keyframe_count = len(animation.get("keyframes") or [])
    samples = as_int(animation.get("samples")) or 0
    return confidence, keyframe_count, samples


def collect_detected_events(
    analysis: Any,
) -> Tuple[List[Dict[str, Any]], int, Dict[str, int]]:
    raw_events: List[Dict[str, Any]] = []

    for node in iter_nodes(analysis):
        if not isinstance(node, dict):
            continue

        animation = node.get("animation")
        cue_id = str(node.get("cue_id") or "").strip()

        if not cue_id or not isinstance(animation, dict):
            continue

        if not bool(animation.get("detected")):
            continue

        animation_type = str(
            animation.get("type") or animation.get("style") or ""
        ).strip().lower()

        if not animation_type:
            continue

        raw_events.append(node)

    deduplicated: Dict[str, Dict[str, Any]] = {}

    for event in raw_events:
        animation = event.get("animation") or {}
        animation_type = str(
            animation.get("type") or animation.get("style") or ""
        ).strip().lower()

        event_id = str(event.get("event_id") or "").strip()
        cue_id = str(event.get("cue_id") or "").strip()

        key = event_id or "|".join(
            [
                cue_id,
                animation_type,
                str(event.get("start")),
                str(event.get("end")),
            ]
        )

        previous = deduplicated.get(key)
        if previous is None or event_quality(event) > event_quality(previous):
            deduplicated[key] = event

    events = list(deduplicated.values())
    events.sort(
        key=lambda row: (
            cue_number(str(row.get("cue_id") or "")),
            str(row.get("event_id") or ""),
        )
    )

    type_counts: Dict[str, int] = {}
    for event in events:
        animation = event.get("animation") or {}
        animation_type = str(
            animation.get("type") or animation.get("style") or "unknown"
        ).strip().lower()
        type_counts[animation_type] = type_counts.get(animation_type, 0) + 1

    return events, len(events), type_counts


def extract_size_candidate(node: Dict[str, Any]) -> Optional[float]:
    direct_keys = (
        "size_after",
        "target_size",
        "calibrated_size",
        "resolved_size",
        "final_size",
        "textplus_size",
    )

    for key in direct_keys:
        candidate = as_float(node.get(key))
        if candidate is not None and candidate > 0:
            return candidate

    after = node.get("after")
    if isinstance(after, dict):
        for key in ("Size", "size", "textplus_size"):
            candidate = as_float(after.get(key))
            if candidate is not None and candidate > 0:
                return candidate

    return None


def collect_v3_rows(*documents: Any) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}

    for document in documents:
        if document is None:
            continue

        for node in iter_nodes(document):
            if not isinstance(node, dict):
                continue

            cue_id = str(node.get("cue_id") or "").strip()
            if not re.fullmatch(r"sub_\d+", cue_id):
                continue

            target = rows.setdefault(cue_id, {"cue_id": cue_id})

            name = str(node.get("name") or node.get("item_name") or "").strip()
            if name.startswith("VC_TEXTPLUS_"):
                target["name"] = name

            for key in (
                "cue_index",
                "style_profile_id",
                "start_frame",
                "end_frame",
                "duration_frames",
                "timeline_frame",
                "timeline_seconds",
                "text",
                "rendered_text",
            ):
                value = node.get(key)
                if value is not None and value != "":
                    target[key] = value

            size_candidate = extract_size_candidate(node)
            if size_candidate is not None:
                target["base_size"] = size_candidate

    cleaned: Dict[str, Dict[str, Any]] = {}

    for cue_id, row in rows.items():
        start_frame = as_int(row.get("start_frame"))
        end_frame = as_int(row.get("end_frame"))
        duration_frames = as_int(row.get("duration_frames"))

        if start_frame is None:
            start_frame = as_int(row.get("timeline_frame"))

        if duration_frames is None and start_frame is not None and end_frame is not None:
            duration_frames = max(0, end_frame - start_frame)

        if end_frame is None and start_frame is not None and duration_frames is not None:
            end_frame = start_frame + duration_frames

        base_size = as_float(row.get("base_size"))

        if (
            start_frame is None
            or duration_frames is None
            or duration_frames <= 0
            or base_size is None
            or base_size <= 0
        ):
            continue

        row["start_frame"] = start_frame
        row["end_frame"] = end_frame
        row["duration_frames"] = duration_frames
        row["base_size"] = base_size

        cleaned[cue_id] = row

    return cleaned


def normalize_source_points(
    animation: Dict[str, Any],
    animation_type: str,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    keyframes = [
        row for row in animation.get("keyframes") or [] if isinstance(row, dict)
    ]

    if len(keyframes) < 2:
        return None, "source_keyframes_missing_or_too_short"

    raw_points: List[Dict[str, Any]] = []

    for row in keyframes:
        relative_time = as_float(row.get("relative_time"))
        timestamp = as_float(row.get("timestamp"))

        raw_points.append(
            {
                "relative_time": relative_time,
                "timestamp": timestamp,
                "scale": as_float(row.get("scale")),
                "position": point_from_value(row.get("position")),
                "opacity": as_float(
                    row.get("opacity", row.get("opacity_proxy"))
                ),
            }
        )

    relative_values = [
        row["relative_time"]
        for row in raw_points
        if row["relative_time"] is not None
    ]

    if len(relative_values) != len(raw_points):
        timestamps = [
            row["timestamp"] for row in raw_points if row["timestamp"] is not None
        ]

        if len(timestamps) != len(raw_points):
            return None, "source_keyframe_time_missing"

        minimum = min(timestamps)
        maximum = max(timestamps)

        if maximum - minimum <= 1e-6:
            return None, "source_keyframe_time_range_zero"

        for row in raw_points:
            row["relative_time"] = (row["timestamp"] - minimum) / (
                maximum - minimum
            )
    else:
        minimum = min(relative_values)
        maximum = max(relative_values)

        if maximum - minimum <= 1e-6:
            return None, "source_relative_time_range_zero"

        for row in raw_points:
            row["relative_time"] = (
                row["relative_time"] - minimum
            ) / (maximum - minimum)

    grouped: Dict[float, List[Dict[str, Any]]] = {}

    for row in raw_points:
        relative_time = max(0.0, min(1.0, float(row["relative_time"])))
        grouped.setdefault(round(relative_time, 6), []).append(row)

    normalized: List[Dict[str, Any]] = []

    for relative_time in sorted(grouped):
        group = grouped[relative_time]

        if animation_type in {"scale", "scale_pop"}:
            values = [row["scale"] for row in group if row["scale"] is not None]

            if not values:
                continue

            if max(values) - min(values) > 0.07:
                return None, "conflicting_duplicate_time_scale_values"

            normalized.append(
                {
                    "relative_time": relative_time,
                    "scale": sum(values) / len(values),
                }
            )

        elif animation_type == "slide":
            positions = [
                row["position"] for row in group if row["position"] is not None
            ]

            if not positions:
                continue

            x_values = [value[0] for value in positions]
            y_values = [value[1] for value in positions]

            if (
                max(x_values) - min(x_values) > 0.025
                or max(y_values) - min(y_values) > 0.025
            ):
                return None, "conflicting_duplicate_time_position_values"

            normalized.append(
                {
                    "relative_time": relative_time,
                    "position": [
                        sum(x_values) / len(x_values),
                        sum(y_values) / len(y_values),
                    ],
                }
            )

    if len(normalized) < 2:
        return None, "insufficient_unique_source_keyframes"

    return normalized, None


def collapse_local_frames(
    keyframes: Sequence[Dict[str, Any]],
    animation_type: str,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    grouped: Dict[int, List[Dict[str, Any]]] = {}

    for row in keyframes:
        grouped.setdefault(int(row["frame"]), []).append(row)

    result: List[Dict[str, Any]] = []

    for frame in sorted(grouped):
        group = grouped[frame]

        if animation_type in {"scale", "scale_pop"}:
            values = [float(row["size_multiplier"]) for row in group]

            if max(values) - min(values) > 0.045:
                return None, "conflicting_values_after_local_frame_quantization"

            result.append(
                {
                    "frame": frame,
                    "relative_time": group[-1]["relative_time"],
                    "size_multiplier": sum(values) / len(values),
                }
            )

        else:
            x_values = [float(row["center_offset"][0]) for row in group]
            y_values = [float(row["center_offset"][1]) for row in group]

            if (
                max(x_values) - min(x_values) > 0.02
                or max(y_values) - min(y_values) > 0.02
            ):
                return None, "conflicting_positions_after_local_frame_quantization"

            result.append(
                {
                    "frame": frame,
                    "relative_time": group[-1]["relative_time"],
                    "center_offset": [
                        sum(x_values) / len(x_values),
                        sum(y_values) / len(y_values),
                    ],
                }
            )

    return result, None


def normalize_animation_event(
    event: Dict[str, Any],
    v3_row: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    animation = event.get("animation") or {}
    animation_type = str(
        animation.get("type") or animation.get("style") or ""
    ).strip().lower()

    if animation_type not in SUPPORTED_TYPES:
        return None, f"unsupported_animation_type:{animation_type or 'missing'}"

    confidence = as_float(animation.get("confidence")) or 0.0
    if confidence < MIN_CONFIDENCE[animation_type]:
        return None, (
            f"confidence_below_threshold:{confidence:.4f}"
            f"<{MIN_CONFIDENCE[animation_type]:.4f}"
        )

    duration_frames = int(v3_row["duration_frames"])
    if duration_frames < 3:
        return None, "target_v3_clip_too_short"

    points, failure = normalize_source_points(animation, animation_type)
    if points is None:
        return None, failure

    local_keyframes: List[Dict[str, Any]] = []

    if animation_type in {"scale", "scale_pop"}:
        if animation_type == "scale_pop" and len(points) < 3:
            return None, "scale_pop_requires_three_unique_source_keyframes"

        stable_scale = as_float(points[-1].get("scale"))
        if stable_scale is None or abs(stable_scale) < 0.20:
            return None, "invalid_stable_scale"

        multipliers: List[float] = []

        for point in points:
            multiplier = float(point["scale"]) / stable_scale
            multipliers.append(multiplier)

        lower_bound, upper_bound = (
            (0.70, 1.35) if animation_type == "scale" else (0.45, 1.40)
        )

        if min(multipliers) < lower_bound or max(multipliers) > upper_bound:
            return None, (
                "source_scale_outlier:"
                f"{min(multipliers):.4f}-{max(multipliers):.4f}"
            )

        minimum_motion = 0.055 if animation_type == "scale" else 0.12
        if max(multipliers) - min(multipliers) < minimum_motion:
            return None, "source_scale_motion_too_small"

        for point, multiplier in zip(points, multipliers):
            frame = int(
                round(float(point["relative_time"]) * (duration_frames - 1))
            )
            local_keyframes.append(
                {
                    "frame": max(0, min(duration_frames - 1, frame)),
                    "relative_time": round(float(point["relative_time"]), 6),
                    "size_multiplier": round(multiplier, 8),
                }
            )

    elif animation_type == "slide":
        final_position = point_from_value(points[-1].get("position"))
        if final_position is None:
            return None, "slide_final_position_missing"

        offsets: List[Tuple[float, float]] = []

        for point in points:
            position = point_from_value(point.get("position"))
            if position is None:
                return None, "slide_position_missing"

            offsets.append(
                (
                    position[0] - final_position[0],
                    position[1] - final_position[1],
                )
            )

        movement = max(math.hypot(x, y) for x, y in offsets)

        if movement < 0.012:
            return None, "source_slide_motion_too_small"

        if movement > 0.13:
            return None, f"source_slide_motion_outlier:{movement:.4f}"

        for point, offset in zip(points, offsets):
            frame = int(
                round(float(point["relative_time"]) * (duration_frames - 1))
            )
            local_keyframes.append(
                {
                    "frame": max(0, min(duration_frames - 1, frame)),
                    "relative_time": round(float(point["relative_time"]), 6),
                    "center_offset": [
                        round(offset[0], 8),
                        round(offset[1], 8),
                    ],
                }
            )

    collapsed, failure = collapse_local_frames(
        local_keyframes,
        animation_type,
    )

    if collapsed is None:
        return None, failure

    required_count = 3 if animation_type == "scale_pop" else 2
    if len(collapsed) < required_count:
        return None, "insufficient_keyframes_after_clip_frame_quantization"

    if collapsed[0]["frame"] != 0:
        return None, "normalized_animation_does_not_start_at_frame_zero"

    if collapsed[-1]["frame"] != duration_frames - 1:
        return None, "normalized_animation_does_not_end_at_clip_end"

    return {
        "source_event_id": event.get("event_id"),
        "cue_id": event.get("cue_id"),
        "style_profile_id": event.get("style_profile_id"),
        "animation_type": animation_type,
        "confidence": confidence,
        "source_start": event.get("start"),
        "source_end": event.get("end"),
        "source_samples": animation.get("samples"),
        "source_reason": animation.get("reason"),
        "keyframes": collapsed,
        "target_keyframe_count": len(collapsed),
    }, None


def prepare_command(args: argparse.Namespace) -> int:
    analysis = load_json(args.analysis)
    size_plan = load_json(args.font_size_plan)
    size_report = load_json(args.font_size_report)

    events, source_detected_count, source_type_counts = collect_detected_events(
        analysis
    )
    v3_rows = collect_v3_rows(size_plan, size_report)

    rejected_events: List[Dict[str, Any]] = []
    accepted_by_cue: Dict[str, List[Dict[str, Any]]] = {}

    for event in events:
        cue_id = str(event.get("cue_id") or "").strip()
        animation = event.get("animation") or {}
        animation_type = str(
            animation.get("type") or animation.get("style") or ""
        ).strip().lower()

        v3_row = v3_rows.get(cue_id)
        if v3_row is None:
            rejected_events.append(
                {
                    "cue_id": cue_id,
                    "event_id": event.get("event_id"),
                    "animation_type": animation_type,
                    "reason": "cue_not_present_in_step_3B_2_v3_map",
                }
            )
            continue

        normalized, failure = normalize_animation_event(event, v3_row)

        if normalized is None:
            rejected_events.append(
                {
                    "cue_id": cue_id,
                    "event_id": event.get("event_id"),
                    "animation_type": animation_type,
                    "confidence": animation.get("confidence"),
                    "reason": failure,
                }
            )
            continue

        accepted_by_cue.setdefault(cue_id, []).append(normalized)

    selected_by_cue: Dict[str, Dict[str, Any]] = {}

    for cue_id, candidates in accepted_by_cue.items():
        candidates.sort(
            key=lambda row: (
                float(row.get("confidence") or 0.0),
                int(row.get("target_keyframe_count") or 0),
            ),
            reverse=True,
        )

        selected_by_cue[cue_id] = candidates[0]

        for candidate in candidates[1:]:
            rejected_events.append(
                {
                    "cue_id": cue_id,
                    "event_id": candidate.get("source_event_id"),
                    "animation_type": candidate.get("animation_type"),
                    "confidence": candidate.get("confidence"),
                    "reason": "lower_ranked_competing_event_for_same_cue",
                }
            )

    plan_items: List[Dict[str, Any]] = []
    selected_type_counts: Dict[str, int] = {}
    target_keyframe_count = 0

    for cue_id in sorted(v3_rows, key=cue_number):
        v3_row = v3_rows[cue_id]
        selected = selected_by_cue.get(cue_id)

        item = {
            "cue_id": cue_id,
            "name": v3_row.get("name"),
            "cue_index": v3_row.get("cue_index"),
            "text": v3_row.get("text") or v3_row.get("rendered_text"),
            "style_profile_id": v3_row.get("style_profile_id"),
            "start_frame": v3_row.get("start_frame"),
            "end_frame": v3_row.get("end_frame"),
            "duration_frames": v3_row.get("duration_frames"),
            "timeline_seconds": v3_row.get("timeline_seconds"),
            "base_size": v3_row.get("base_size"),
            "selected": bool(selected),
            "animation": selected,
        }

        if selected:
            animation_type = str(selected["animation_type"])
            selected_type_counts[animation_type] = (
                selected_type_counts.get(animation_type, 0) + 1
            )
            target_keyframe_count += int(
                selected.get("target_keyframe_count") or 0
            )

        plan_items.append(item)

    checks = {
        "expected_v3_count": len(v3_rows) == args.expected_v3_count,
        "expected_source_detected_count": (
            args.expected_source_detected <= 0
            or source_detected_count == args.expected_source_detected
        ),
        "selected_animation_count_nonzero": bool(selected_by_cue),
        "all_selected_cues_exist_in_v3": all(
            cue_id in v3_rows for cue_id in selected_by_cue
        ),
        "target_keyframe_count_nonzero": target_keyframe_count > 0,
    }

    plan_core = {
        "schema": SCHEMA,
        "schema_version": "1.0",
        "version": VERSION,
        "inputs": {
            "analysis": str(Path(args.analysis)),
            "analysis_sha256": file_sha256(args.analysis),
            "font_size_plan": str(Path(args.font_size_plan)),
            "font_size_plan_sha256": file_sha256(args.font_size_plan),
            "font_size_report": str(Path(args.font_size_report)),
            "font_size_report_sha256": file_sha256(args.font_size_report),
        },
        "expected_v3_count": args.expected_v3_count,
        "summary": {
            "v3_item_count": len(v3_rows),
            "source_detected_event_count": source_detected_count,
            "source_animation_type_counts": source_type_counts,
            "selected_animation_count": len(selected_by_cue),
            "selected_animation_type_counts": selected_type_counts,
            "rejected_event_count": len(rejected_events),
            "static_v3_count": len(v3_rows) - len(selected_by_cue),
            "target_keyframe_count": target_keyframe_count,
        },
        "items": plan_items,
        "rejected_events": rejected_events,
        "visual_review_samples": [
            {
                "cue_id": row["cue_id"],
                "name": row.get("name"),
                "text": row.get("text"),
                "start_frame": row.get("start_frame"),
                "timeline_seconds": row.get("timeline_seconds"),
                "animation_type": (
                    row.get("animation") or {}
                ).get("animation_type"),
            }
            for row in plan_items
            if row.get("selected")
        ][:12],
        "checks": checks,
    }

    plan_hash = json_hash(plan_core)
    plan = {
        "ok": all(checks.values()),
        "plan_hash": plan_hash,
        **plan_core,
    }

    validation = {
        "ok": bool(plan["ok"]),
        "step": "Major Step 3C — planning",
        "version": VERSION,
        "plan": str(Path(args.output)),
        "plan_hash": plan_hash,
        "summary": plan["summary"],
        "checks": checks,
        "failures": [key for key, passed in checks.items() if not passed],
    }

    write_json(args.output, plan)
    write_json(args.validation, validation)

    print(json.dumps(validation, ensure_ascii=False, indent=2))

    if validation["ok"]:
        print()
        print(
            "PASS: Step 3C source animation plan is normalized and ready "
            "for Resolve."
        )
        return 0

    print()
    print("ERROR: Step 3C plan validation failed.")
    return 1


def validate_command(args: argparse.Namespace) -> int:
    plan = load_json(args.plan)
    report = load_json(args.report)

    plan_summary = plan.get("summary") or {}
    summary = report.get("summary") or {}

    selected_count = int(plan_summary.get("selected_animation_count") or 0)
    expected_keyframes = int(plan_summary.get("target_keyframe_count") or 0)

    checks = {
        "plan_ok": bool(plan.get("ok")),
        "report_ok": bool(report.get("ok")),
        "plan_hash_match": report.get("plan_hash") == plan.get("plan_hash"),
        "expected_v3_count": (
            int(summary.get("v3_candidate_count") or 0)
            == int(plan.get("expected_v3_count") or 0)
        ),
        "plan_item_count": (
            int(summary.get("plan_item_count") or 0)
            == int(plan_summary.get("v3_item_count") or 0)
        ),
        "selected_count": (
            int(summary.get("selected_animation_count") or 0)
            == selected_count
        ),
        "mapped_count": int(summary.get("mapped_count") or 0) == selected_count,
        "readback_success_count": (
            int(summary.get("readback_success_count") or 0)
            == selected_count
        ),
        "readback_keyframe_count": (
            int(summary.get("readback_keyframe_count") or 0)
            == expected_keyframes
        ),
        "failed_count": int(summary.get("failed_count") or 0) == 0,
        "font_integrity_failure_count": (
            int(summary.get("font_integrity_failure_count") or 0) == 0
        ),
        "timeline_integrity_failure_count": (
            int(summary.get("timeline_integrity_failure_count") or 0) == 0
        ),
        "core_track_integrity": bool(
            (report.get("core_track_integrity") or {}).get("ok")
        ),
        "v3_track_integrity": bool(
            (report.get("v3_track_integrity") or {}).get("ok")
        ),
        "keyframe_presence_verified": bool(
            summary.get("keyframe_presence_verified")
        ),
    }

    if args.mode == "first_application_pass":
        checks.update(
            {
                "first_run_modified_count": (
                    int(summary.get("modified_count") or 0) == selected_count
                ),
                "first_run_already_correct_count": (
                    int(summary.get("already_correct_count") or 0) == 0
                ),
                "first_run_keyframes_written": (
                    int(summary.get("keyframes_written_count") or 0)
                    == expected_keyframes
                ),
            }
        )

    elif args.mode == "idempotent_second_run":
        checks.update(
            {
                "second_run_modified_count": (
                    int(summary.get("modified_count") or 0) == 0
                ),
                "second_run_already_correct_count": (
                    int(summary.get("already_correct_count") or 0)
                    == selected_count
                ),
                "second_run_keyframes_written": (
                    int(summary.get("keyframes_written_count") or 0) == 0
                ),
            }
        )

    failures = [key for key, passed in checks.items() if not passed]

    validation = {
        "ok": not failures,
        "step": "Major Step 3C",
        "validator_version": VERSION,
        "mode": args.mode,
        "plan": str(Path(args.plan)),
        "report": str(Path(args.report)),
        "selected_animation_count": selected_count,
        "expected_keyframe_count": expected_keyframes,
        "summary": summary,
        "checks": checks,
        "failures": failures,
        "output": str(Path(args.output)),
    }

    write_json(args.output, validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))

    if validation["ok"]:
        if args.mode == "first_application_pass":
            print()
            print(
                "PASS: Step 3C applied and read back all selected source "
                "caption animations."
            )
        else:
            print()
            print(
                "PASS: Step 3C second run is idempotent; existing source "
                "animation keyframes were reused without writes."
            )
        return 0

    print()
    print("ERROR: Step 3C validation failed.")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Video Cloner Major Step 3C planner and validator."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--analysis", required=True)
    prepare.add_argument("--font-size-plan", required=True)
    prepare.add_argument("--font-size-report", required=True)
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--validation", required=True)
    prepare.add_argument("--expected-v3-count", type=int, default=116)
    prepare.add_argument("--expected-source-detected", type=int, default=0)

    validate = subparsers.add_parser("validate")
    validate.add_argument(
        "--mode",
        required=True,
        choices=("first_application_pass", "idempotent_second_run"),
    )
    validate.add_argument("--plan", required=True)
    validate.add_argument("--report", required=True)
    validate.add_argument("--output", required=True)

    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.command == "prepare":
        return prepare_command(args)

    if args.command == "validate":
        return validate_command(args)

    raise RuntimeError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "version": VERSION,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(1)