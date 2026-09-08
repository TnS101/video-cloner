#!/usr/bin/env python3
"""Build a visual-first caption-layer lifecycle authority plan.

Visual evidence owns layer presence, timing, persistence, overlap, and exit
behavior. Transcript cues own canonical text and provide timing only when visual
lifecycle evidence is missing or ambiguous.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

VERSION = "caption_lifecycle_authority_step_3D_v1_0_visual_primary"
SCHEMA = "video_cloner_caption_lifecycle_authority_plan"
AUTHORITY_POLICY = "VISUAL_PRIMARY_TRANSCRIPT_TEXT_AND_TIMING_FALLBACK"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def as_int(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def unique_index(rows: Iterable[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "").strip()
        if not value:
            raise ValueError(f"missing_{label}_{key}")
        if value in result:
            raise ValueError(f"duplicate_{label}_{key}:{value}")
        result[value] = row
    return result


def opacity_envelope(observations: list[dict[str, Any]]) -> dict[str, Any]:
    points: list[tuple[int, float]] = []
    for row in observations:
        frame = as_int(row.get("timeline_frame"))
        opacity = as_float(row.get("opacity_proxy"))
        if frame is not None and opacity is not None:
            points.append((frame, max(0.0, opacity)))
    points.sort()
    if not points:
        return {
            "available": False,
            "sample_count": 0,
            "fade_in_detected": False,
            "fade_out_detected": False,
            "enter_end_frame": None,
            "exit_start_frame": None,
        }

    peak = max(value for _, value in points)
    if peak <= 0:
        return {
            "available": True,
            "sample_count": len(points),
            "first_opacity": points[0][1],
            "peak_opacity": peak,
            "last_opacity": points[-1][1],
            "fade_in_detected": False,
            "fade_out_detected": False,
            "enter_end_frame": points[0][0],
            "exit_start_frame": None,
        }

    threshold = peak * 0.90
    stable_frames = [frame for frame, value in points if value >= threshold]
    enter_end = stable_frames[0] if stable_frames else points[0][0]
    exit_start = stable_frames[-1] + 1 if stable_frames and stable_frames[-1] < points[-1][0] else None

    first = points[0][1]
    last = points[-1][1]
    early = [value for _, value in points[: min(4, len(points))]]
    late = [value for _, value in points[max(0, len(points) - 4) :]]
    fade_in = (
        len(early) >= 2
        and first <= peak * 0.70
        and early[-1] > early[0]
    )
    fade_out = (
        len(late) >= 2
        and last <= peak * 0.70
        and late[-1] < late[0]
    )
    return {
        "available": True,
        "sample_count": len(points),
        "first_opacity": round(first, 6),
        "peak_opacity": round(peak, 6),
        "last_opacity": round(last, 6),
        "fade_in_detected": fade_in,
        "fade_out_detected": fade_out,
        "enter_end_frame": enter_end,
        "exit_start_frame": exit_start if fade_out else None,
    }


def intervals_overlap(left: list[int], right: list[int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def build_plan(visual_document: dict[str, Any], caption_plan: dict[str, Any]) -> dict[str, Any]:
    plan_items = caption_plan.get("items")
    track_rows = visual_document.get("tracks")
    if not isinstance(plan_items, list) or not isinstance(track_rows, list):
        raise ValueError("inputs_require_items_and_tracks")

    plan_rows = [row for row in plan_items if isinstance(row, dict)]
    visual_rows = [row for row in track_rows if isinstance(row, dict)]
    plan_by_cue = unique_index(plan_rows, "cue_id", "caption_plan")
    visual_by_cue = unique_index(visual_rows, "cue_id", "visual_track")

    transcript_windows: dict[str, list[int]] = {}
    for cue_id, row in plan_by_cue.items():
        start = as_int(row.get("start_frame"))
        end = as_int(row.get("end_frame"))
        if start is None or end is None or end <= start:
            raise ValueError(f"invalid_transcript_window:{cue_id}")
        transcript_windows[cue_id] = [start, end]

    layers: list[dict[str, Any]] = []
    mandatory_redetection: list[dict[str, Any]] = []

    for cue_id, plan_row in sorted(
        plan_by_cue.items(), key=lambda pair: as_int(pair[1].get("cue_index")) or 10**9
    ):
        transcript_window = transcript_windows[cue_id]
        track = visual_by_cue.get(cue_id)
        geometry = track.get("geometry") if isinstance(track, dict) else None
        accepted = bool(track and track.get("accepted_source_instance"))
        first_visible = as_int((geometry or {}).get("first_visible_frame")) if isinstance(geometry, dict) else None
        last_visible = as_int((geometry or {}).get("last_visible_frame")) if isinstance(geometry, dict) else None
        visual_valid = accepted and first_visible is not None and last_visible is not None and last_visible >= first_visible
        animation_selected = bool(plan_row.get("selected"))

        if visual_valid:
            lifecycle_window = [first_visible, last_visible + 1]
            timing_authority = "visual_primary"
            lifecycle_status = "source_observed"
            requires_redetection = False
            confidence = track.get("confidence") or {}
            observations = [
                row for row in (track.get("frame_observations") or []) if isinstance(row, dict)
            ]
            envelope = opacity_envelope(observations)
        else:
            lifecycle_window = list(transcript_window)
            timing_authority = "transcript_fallback"
            lifecycle_status = "visual_lifecycle_missing_or_ambiguous"
            requires_redetection = animation_selected
            confidence = (track or {}).get("confidence") or {}
            envelope = opacity_envelope([])

        layer = {
            "layer_id": f"caption_layer_{cue_id}",
            "cue_id": cue_id,
            "cue_index": as_int(plan_row.get("cue_index")),
            "name": str(plan_row.get("name") or ""),
            "text": str(plan_row.get("text") or ""),
            "text_authority": "transcript_primary",
            "timing_authority": timing_authority,
            "transcript_window": transcript_window,
            "lifecycle_window": lifecycle_window,
            "lifecycle_status": lifecycle_status,
            "animation_selected_step_3C": animation_selected,
            "animation_type_step_3C": (
                str((plan_row.get("animation") or {}).get("animation_type") or "") or None
            ),
            "visual_track_available": track is not None,
            "visual_track_accepted": visual_valid,
            "visual_source_exactness": (track or {}).get("source_exactness"),
            "visual_confidence_label": confidence.get("label") if isinstance(confidence, dict) else None,
            "visual_dense_observation_count": (
                as_int(confidence.get("dense_observation_count")) if isinstance(confidence, dict) else None
            ),
            "starts_before_transcript_frames": max(0, transcript_window[0] - lifecycle_window[0]),
            "starts_after_transcript_frames": max(0, lifecycle_window[0] - transcript_window[0]),
            "ends_after_transcript_frames": max(0, lifecycle_window[1] - transcript_window[1]),
            "ends_before_transcript_frames": max(0, transcript_window[1] - lifecycle_window[1]),
            "crosses_transcript_boundaries": lifecycle_window != transcript_window,
            "opacity_envelope": envelope,
            "requires_visual_lifecycle_redetection": requires_redetection,
            "calibration_priority": "mandatory" if requires_redetection else "none",
            "concurrent_transcript_cue_ids": [],
            "concurrent_visual_layer_ids": [],
        }
        if requires_redetection:
            mandatory_redetection.append(
                {
                    "cue_id": cue_id,
                    "name": layer["name"],
                    "text": layer["text"],
                    "reason": "step_3C_animation_selected_without_accepted_visual_lifecycle",
                    "transcript_window": transcript_window,
                    "required_detection": [
                        "visual_first_frame",
                        "visual_last_frame",
                        "layer_overlap",
                        "entry_motion",
                        "hold_phase",
                        "exit_motion",
                        "opacity_envelope",
                    ],
                }
            )
        layers.append(layer)

    by_id = {row["layer_id"]: row for row in layers}
    visual_layers = [row for row in layers if row["timing_authority"] == "visual_primary"]
    overlap_pairs: list[list[str]] = []

    for layer in layers:
        layer["concurrent_transcript_cue_ids"] = [
            other_cue
            for other_cue, window in transcript_windows.items()
            if other_cue != layer["cue_id"] and intervals_overlap(layer["lifecycle_window"], window)
        ]

    for index, left in enumerate(visual_layers):
        for right in visual_layers[index + 1 :]:
            if intervals_overlap(left["lifecycle_window"], right["lifecycle_window"]):
                left["concurrent_visual_layer_ids"].append(right["layer_id"])
                right["concurrent_visual_layer_ids"].append(left["layer_id"])
                overlap_pairs.append([left["layer_id"], right["layer_id"]])

    for row in layers:
        row["concurrent_transcript_cue_ids"].sort()
        row["concurrent_visual_layer_ids"].sort()

    selected = [row for row in layers if row["animation_selected_step_3C"]]
    summary = {
        "caption_layer_count": len(layers),
        "visual_primary_count": sum(row["timing_authority"] == "visual_primary" for row in layers),
        "transcript_fallback_count": sum(row["timing_authority"] == "transcript_fallback" for row in layers),
        "visual_differs_from_transcript_count": sum(
            row["timing_authority"] == "visual_primary"
            and row["lifecycle_window"] != row["transcript_window"]
            for row in layers
        ),
        "visual_extends_outside_transcript_count": sum(
            row["timing_authority"] == "visual_primary"
            and (
                row["lifecycle_window"][0] < row["transcript_window"][0]
                or row["lifecycle_window"][1] > row["transcript_window"][1]
            )
            for row in layers
        ),
        "visual_fully_contained_count": sum(
            row["timing_authority"] == "visual_primary"
            and row["lifecycle_window"][0] >= row["transcript_window"][0]
            and row["lifecycle_window"][1] <= row["transcript_window"][1]
            for row in layers
        ),
        "visual_concurrent_overlap_pair_count": len(overlap_pairs),
        "selected_animation_count": len(selected),
        "selected_animation_visual_primary_count": sum(
            row["timing_authority"] == "visual_primary" for row in selected
        ),
        "selected_animation_missing_visual_lifecycle_count": sum(
            row["timing_authority"] == "transcript_fallback" for row in selected
        ),
        "mandatory_redetection_count": len(mandatory_redetection),
        "mandatory_redetection_cue_ids": [row["cue_id"] for row in mandatory_redetection],
    }

    checks = {
        "caption_count_matches_plan": summary["caption_layer_count"] == len(plan_rows),
        "authority_partition": (
            summary["visual_primary_count"] + summary["transcript_fallback_count"]
            == summary["caption_layer_count"]
        ),
        "text_always_transcript_primary": all(
            row["text_authority"] == "transcript_primary" for row in layers
        ),
        "visual_lifecycle_not_clamped_to_transcript": all(
            row["lifecycle_window"]
            == [
                as_int((visual_by_cue[row["cue_id"]].get("geometry") or {}).get("first_visible_frame")),
                as_int((visual_by_cue[row["cue_id"]].get("geometry") or {}).get("last_visible_frame")) + 1,
            ]
            for row in visual_layers
        ),
        "overlap_allowed": True,
        "selected_animation_redetection_partition": (
            summary["selected_animation_visual_primary_count"]
            + summary["selected_animation_missing_visual_lifecycle_count"]
            == summary["selected_animation_count"]
        ),
    }

    result = {
        "ok": all(checks.values()),
        "schema": SCHEMA,
        "schema_version": 1,
        "version": VERSION,
        "authority_policy": AUTHORITY_POLICY,
        "policy": {
            "visual_analysis_role": "Primary authority for caption-layer presence, lifecycle timing, persistence, overlap, stacking, entry, hold, and exit behavior.",
            "transcript_role": "Primary authority for canonical text and semantic anchoring; timing fallback only when visual lifecycle evidence is missing or ambiguous.",
            "non_clamping_rule": "Observed visual lifecycle must never be truncated to transcript cue boundaries.",
            "concurrency_rule": "Multiple caption layers may coexist and animate independently.",
            "modern_caption_model": [
                "entry",
                "hold",
                "persistent_emphasis",
                "replacement_or_accumulation",
                "custom_exit",
                "overlapping_layers",
            ],
        },
        "inputs": {
            "visual_tracks_semantic_sha256": canonical_hash(visual_document),
            "caption_plan_semantic_sha256": canonical_hash(caption_plan),
        },
        "summary": summary,
        "mandatory_visual_redetection_queue": mandatory_redetection,
        "visual_overlap_pairs": overlap_pairs,
        "layers": layers,
        "checks": checks,
    }
    result["plan_semantic_sha256"] = canonical_hash(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--visual-tracks", type=Path, required=True)
    parser.add_argument("--caption-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build_plan(load_json(args.visual_tracks), load_json(args.caption_plan))
        write_json(args.output, result)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps({"ok": result["ok"], "summary": result["summary"]}, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
