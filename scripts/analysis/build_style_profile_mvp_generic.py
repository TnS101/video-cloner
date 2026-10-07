#!/usr/bin/env python3
"""Compile generic analysis artifacts into the minimal MVP style profile."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import mean, median, quantiles
from typing import Any


DEFERRED = ["flash_execution", "generic_vfx", "occlusion_reconstruction", "sfx", "graphics"]


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, str]:
    return {"path": path.as_posix(), "sha256": _sha256(path)}


def _compact_transition(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "from_shot": row.get("from_shot"),
        "to_shot": row.get("to_shot"),
        "cut_frame": row.get("cut_frame"),
        "cut_time_seconds": row.get("cut_time"),
        "family": row.get("transition_type") or "UNKNOWN",
        "duration_frames": row.get("duration_frames"),
        "confidence": row.get("confidence") or "UNKNOWN",
    }


def _pace_family(median_seconds: float) -> str:
    if median_seconds <= 1.5:
        return "fast_cut"
    if median_seconds <= 3.0:
        return "medium_cut"
    return "long_hold"


def build_profile(
    analysis_path: Path,
    edit_plan_path: Path,
    transitions_path: Path,
    camera_path: Path,
    caption_grammar_path: Path,
    reel_id: str,
) -> dict[str, Any]:
    analysis = _load(analysis_path)
    plan = _load(edit_plan_path)
    transitions = _load(transitions_path)
    camera = _load(camera_path)
    captions = _load(caption_grammar_path)
    if not analysis.get("success") or not transitions.get("success"):
        raise ValueError("Analysis and transition inputs must be successful")
    identities = {analysis.get("job", {}).get("job_id"), plan.get("video_id"), captions.get("source_reel")}
    if identities != {reel_id}:
        raise ValueError(f"Input Reel identities do not match {reel_id}: {sorted(str(value) for value in identities)}")

    shots = analysis.get("timeline", {}).get("shots") or []
    if not shots:
        raise ValueError("Merged analysis contains no shots")
    durations = [float(row["duration_seconds"]) for row in shots]
    quartiles = quantiles(durations, n=4, method="inclusive")
    distribution = {
        "min": round(min(durations), 4),
        "p25": round(quartiles[0], 4),
        "median": round(median(durations), 4),
        "mean": round(mean(durations), 4),
        "p75": round(quartiles[2], 4),
        "max": round(max(durations), 4),
    }
    sync_count = sum(
        any(bool(action.get("compiler_hints", {}).get("sync_to_beat")) for action in row.get("actions", []))
        for row in plan.get("timeline", [])
    )

    transition_rows = transitions.get("transitions") or []
    family_counts = dict(sorted(Counter(row.get("transition_type", "UNKNOWN") for row in transition_rows).items()))
    candidates = [row for row in transition_rows if str(row.get("transition_type", "")).endswith("_candidate") or not row.get("editor_actionable")]
    detector_actionable = [row for row in transition_rows if row.get("editor_actionable") and row not in candidates]
    merged_rows = analysis.get("timeline", {}).get("transitions") or []
    merged_actionable = [row for row in merged_rows if row.get("is_editor_candidate")]
    if len(merged_actionable) != int(analysis.get("summary", {}).get("actionable_transitions_count", 0)):
        raise ValueError("Merged actionable transition count does not match merged authority")

    keyframes = camera.get("editor_transform", {}).get("keyframes") or []
    zooms = [float(row["zoom"]) for row in keyframes if row.get("zoom") is not None]
    color = captions["color_opacity_rules"]
    caption_count = captions["persistence_rules"]["caption_count"]
    common_combos = [row for row in captions["enter_exit_combos"] if row["caption_count"] >= 3]
    rare_combo_count = sum(row["caption_count"] for row in captions["enter_exit_combos"] if row["caption_count"] < 3)
    duration = float(analysis["job"]["duration_seconds"])

    return {
        "schema": "video_cloner.style_profile.mvp.v1",
        "reel_id": reel_id,
        "cuts_pacing": {
            "observed": {
                "duration_sec": duration,
                "fps": analysis["job"]["fps"],
                "cut_count": len(shots) - 1,
                "shot_count": len(shots),
                "shot_duration_distribution_sec": distribution,
                "source_pace_label": plan.get("global_style", {}).get("pace") or "UNKNOWN",
                "derived_pacing_family": _pace_family(distribution["median"]),
                "music_sync": plan.get("global_style", {}).get("music_sync"),
                "beat_sync_shot_count": sync_count,
            },
            "recommended": {
                "pacing_summary": f"{_pace_family(distribution['median'])} rhythm with a {distribution['median']:.4f}s median shot",
                "cut_rules": ["prefer source-backed shot boundaries", "preserve source timing for candidate-only retimes"],
            },
            "unresolved": ["retime execution is not authoritative"],
        },
        "transitions": {
            "observed": {
                "families_present": family_counts,
                "confidence_counts": transitions.get("transition_summary", {}).get("confidence_counts", {}),
                "event_count": len(transition_rows),
                "density_per_minute": round(len(transition_rows) / duration * 60, 4),
                "detector_actionable_events": [_compact_transition(row) for row in detector_actionable],
                "candidate_only_events": [_compact_transition(row) for row in candidates],
            },
            "recommended": {
                "merged_conservative_events": [_compact_transition(row) for row in merged_actionable],
                "timing_rule": "retain measured cut time and duration only for merged conservative authority",
                "candidate_rule": "candidate events remain analysis-only and are never promoted",
            },
            "deferred_unknown": {
                "candidate_execution": "unsupported",
                "physical_effect_reconstruction": "unknown",
            },
        },
        "camera": {
            "observed": {
                "framing": camera.get("framing") or "UNKNOWN",
                "subject_lock": camera.get("subject_lock"),
                "subject_observation": camera.get("subject_observation") or {},
                "camera_motion": camera.get("camera_motion") or {},
                "punch_in_events": camera.get("punch_in_events") or [],
                "punch_out_events": camera.get("punch_out_events") or [],
                "pan_events": camera.get("pan_events") or [],
                "stabilization": camera.get("stabilization") or "UNKNOWN",
            },
            "recommended": {
                "reframe_strategy": camera.get("reframe_strategy") or "UNKNOWN",
                "editor_transform": {
                    "operation": camera.get("editor_transform", {}).get("operation") or "UNKNOWN",
                    "authority": camera.get("editor_transform", {}).get("authority") or "UNKNOWN",
                    "sample_count": len(keyframes),
                    "zoom_range": [min(zooms), max(zooms)] if zooms else None,
                    "rule": "reframe toward sampled face centers without claiming physical camera provenance",
                },
            },
            "unresolved": ["physical camera motion versus baked editor transform"],
            "confidence": camera.get("confidence", 0.0),
        },
        "captions": {
            "observed": {
                "style_families": captions["caption_style_families"],
                "persistence_rules": captions["persistence_rules"],
                "font_rules": captions["font_rules"],
                "color_rules": {
                    "known_style_family_fill_count": sum(color.get("profile_fill_colors", {}).values()),
                    "median_text_color": color.get("measured_reel_median_text_color"),
                    "median_stroke_color": color.get("measured_reel_median_stroke_color"),
                    "dark_stroke_ratio": color.get("measured_dark_stroke_ratio"),
                    "stroke_presence": color.get("profile_stroke_presence", {}),
                },
                "opacity_rules": {
                    "rule": color.get("opacity_rule"),
                    "status": color.get("fill_opacity", {}).get("evidence_status", "UNKNOWN"),
                    "unresolved_count": captions["unresolved"]["opacity_count"],
                },
                "layout_rules": captions["layout_rules"],
                "animation_families": captions["animation_families"],
                "enter_exit_combos": {"common": common_combos, "rare_caption_count": rare_combo_count},
            },
            "recommended": {
                "transfer_rule": "reuse observed weight, layout, persistence, and normalized animation families",
            },
            "unresolved": captions["unresolved"],
            "confidence": captions["confidence"],
        },
        "deferred": DEFERRED,
        "source_artifacts": {
            "analysis": _source(analysis_path),
            "edit_plan": _source(edit_plan_path),
            "transitions": _source(transitions_path),
            "camera": _source(camera_path),
            "captions": _source(caption_grammar_path),
        },
        "confidence": {
            "status": "MVP_READY_WITH_EXPLICIT_LIMITATIONS",
            "cuts_pacing": "generic_analysis",
            "transitions": "generic_analysis_with_conservative_authority",
            "camera": camera.get("confidence", 0.0),
            "captions": captions["confidence"]["overall"],
            "overall": "medium_high",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--edit-plan", type=Path, required=True)
    parser.add_argument("--transitions", type=Path, required=True)
    parser.add_argument("--camera", type=Path, required=True)
    parser.add_argument("--caption-grammar", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reel-id", required=True)
    args = parser.parse_args()
    profile = build_profile(args.analysis, args.edit_plan, args.transitions, args.camera, args.caption_grammar, args.reel_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(args.output), "reel_id": args.reel_id}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
