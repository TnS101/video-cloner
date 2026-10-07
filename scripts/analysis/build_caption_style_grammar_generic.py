#!/usr/bin/env python3
"""Compile generic flattened-video caption evidence into a reusable grammar."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any


ANIMATION_FAMILY = {
    "static": "static",
    "fade": "fade",
    "slide": "slide",
    "scale": "scale",
    "bounce": "bounce_overshoot",
    "overshoot": "bounce_overshoot",
    "scale_overshoot": "bounce_overshoot",
    "pop_fade": "combination",
    "scale_pop": "combination",
    "slide_fade": "combination",
    "combination": "combination",
}


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _status(value: Any, *, inferred: bool = False) -> str:
    if value is None or value == "" or str(value).lower() in {"unknown", "normal_or_unknown"}:
        return "UNKNOWN"
    return "INFERRED" if inferred else "OBSERVED"


def _counts(values: list[Any]) -> dict[str, int]:
    return dict(sorted(Counter("UNKNOWN" if _status(value) == "UNKNOWN" else str(value) for value in values).items()))


def _duration_stats(values: list[float]) -> dict[str, float | None]:
    return {
        "min": round(min(values), 4) if values else None,
        "median": round(median(values), 4) if values else None,
        "max": round(max(values), 4) if values else None,
    }


def normalize_animation_hint(hint: Any) -> str:
    return ANIMATION_FAMILY.get(str(hint or "").lower(), "unresolved")


def _style_family(profile: dict[str, Any], event_count: int) -> dict[str, Any]:
    typography = profile.get("typography") or {}
    placement = profile.get("placement") or {}
    colors = profile.get("colors") or {}
    stroke = profile.get("stroke") or {}
    shadow = profile.get("shadow") or {}
    font = typography.get("font_family")
    return {
        "family": profile.get("style_id") or "unresolved",
        "role": profile.get("role") or "UNKNOWN",
        "caption_count": event_count,
        "sample_count": profile.get("sample_count", 0),
        "confidence": profile.get("confidence") or {"score": 0.0, "label": "unknown"},
        "font_family_candidates": _counts([font]),
        "font_family_status": _status(font),
        "font_weight": typography.get("font_weight") or "UNKNOWN",
        "font_style": typography.get("font_style") or "UNKNOWN",
        "median_height_px": typography.get("font_height_px"),
        "median_height_ratio": typography.get("font_height_ratio"),
        "case_style": typography.get("case_style") or "UNKNOWN",
        "density": typography.get("density") or {},
        "fill_color": colors.get("fill"),
        "stroke": {
            "enabled": stroke.get("enabled"),
            "color": stroke.get("color") or colors.get("stroke"),
            "width_px_estimate": stroke.get("width_px_estimate"),
            "evidence_status": _status(stroke.get("enabled"), inferred=True),
        },
        "shadow": {
            "enabled": shadow.get("enabled"),
            "color": shadow.get("color") or colors.get("shadow"),
            "opacity_estimate": shadow.get("opacity_estimate"),
            "blur_px_estimate": shadow.get("blur_px_estimate"),
            "evidence_status": _status(shadow.get("enabled"), inferred=True),
        },
        "fill_opacity": {"value": None, "evidence_status": "UNKNOWN"},
        "layout": {
            "position": placement.get("position") or "UNKNOWN",
            "vertical_zone": placement.get("vertical_zone") or "UNKNOWN",
            "horizontal_align": placement.get("horizontal_align") or "UNKNOWN",
            "anchor": placement.get("anchor"),
        },
        "rule": "reuse measured profile attributes; unknown values remain unresolved",
    }


def _event_evidence(event: dict[str, Any]) -> dict[str, Any]:
    animation = event.get("animation") or {}
    hint = animation.get("type") or animation.get("style")
    family = normalize_animation_hint(hint)
    typography = event.get("typography") or {}
    colors = event.get("colors") or {}
    stroke = event.get("stroke") or {}
    placement = event.get("placement") or {}
    start = event.get("start")
    end = event.get("end")
    duration = event.get("duration")
    if duration is None and start is not None and end is not None:
        duration = round(float(end) - float(start), 4)
    unresolved_boundary = {
        "family": "unresolved",
        "source_label": "UNRESOLVED",
        "direction": "unknown",
        "easing_category": "unknown",
        "intensity": "unknown",
        "confidence": 0.0,
        "evidence_status": "UNKNOWN",
        "reason": "event-level samples do not isolate this boundary",
    }
    return {
        "identity": event.get("event_id") or event.get("visual_event_identity") or "UNKNOWN",
        "style_family": event.get("style_profile_id") or "unresolved",
        "timing": {
            "start_seconds": start,
            "end_seconds_exclusive": end,
            "duration_seconds": duration,
            "persistence": "continuous_visible_interval",
            "interval_semantics": event.get("visibility_interval_semantics") or "half_open",
            "evidence_status": "OBSERVED" if event.get("observed_start") is not None else "INFERRED",
        },
        "animation": {
            "observed_family": family,
            "source_hint": hint or "UNRESOLVED",
            "source_confidence": animation.get("confidence", 0.0),
            "source_samples": animation.get("samples", 0),
            "source_evidence_status": "UNKNOWN" if family == "unresolved" else "INFERRED",
            "enter": dict(unresolved_boundary),
            "hold": {
                "behavior": "continuous_visible_interval",
                "duration_seconds": duration,
                "evidence_status": "INFERRED",
            },
            "exit": dict(unresolved_boundary),
            "combo": "unresolved->continuous_hold->unresolved",
            "entry_exit_relationship": "UNKNOWN",
        },
        "style": {
            "font_family_candidate": None if _status(typography.get("font_family")) == "UNKNOWN" else typography.get("font_family"),
            "font_family_status": _status(typography.get("font_family")),
            "font_style_candidate": typography.get("font_style"),
            "weight": typography.get("font_weight"),
            "median_height_px": typography.get("font_height_px"),
            "font_height_ratio": typography.get("font_height_ratio"),
            "fill_color": colors.get("fill"),
            "fill_color_status": _status(colors.get("fill"), inferred=True),
            "opacity": None,
            "opacity_status": "UNKNOWN",
            "stroke_presence": stroke.get("enabled"),
            "stroke_status": _status(stroke.get("enabled"), inferred=True),
            "center": placement.get("anchor"),
        },
        "provenance": {
            "source": event.get("source") or "caption_style_event",
            "label_source": event.get("label_source") or "UNKNOWN",
            "confidence": event.get("confidence") or {},
        },
    }


def build_grammar(caption_style_path: Path, reel_id: str) -> dict[str, Any]:
    source = _load(caption_style_path)
    if not source.get("success"):
        raise ValueError("Caption style analysis is not successful")
    profiles = source.get("caption_style_profiles") or source.get("style_profiles") or []
    events = source.get("caption_style_events") or source.get("style_events") or []
    if not profiles or not events:
        raise ValueError("Caption style analysis must contain profiles and timed style events")

    event_profile_counts = Counter(event.get("style_profile_id") or "unresolved" for event in events)
    families = [_style_family(profile, event_profile_counts[profile.get("style_id")]) for profile in profiles]
    evidence = [_event_evidence(event) for event in events]
    source_hint_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for event in events:
        animation = event.get("animation") or {}
        hint = animation.get("type") or animation.get("style") or "UNRESOLVED"
        source_hint_counts[normalize_animation_hint(hint)][str(hint)] += 1
    animation_families = [
        {
            "family": family,
            "boundary_count": sum(hints.values()),
            "source_hint_counts": dict(sorted(hints.items())),
            "evidence_status": "UNKNOWN" if family == "unresolved" else "INFERRED",
            "rule": "nearest reusable family from event-level adjacent-frame evidence",
        }
        for family, hints in sorted(source_hint_counts.items())
    ]

    durations = [float(row["timing"]["duration_seconds"]) for row in evidence if row["timing"]["duration_seconds"] is not None]
    summary = source.get("summary") or source.get("subtitle_style_summary") or {}
    resolved = source.get("caption_style_resolved") or source.get("resolved") or {}
    resolved_typography = resolved.get("typography") or {}
    fonts = [(profile.get("typography") or {}).get("font_family") for profile in profiles]
    styles = [(profile.get("typography") or {}).get("font_style") for profile in profiles]
    weights = [(profile.get("typography") or {}).get("font_weight") for profile in profiles]
    fills = [(profile.get("colors") or {}).get("fill") for profile in profiles]
    strokes = [(profile.get("stroke") or {}).get("enabled") for profile in profiles]
    unknown_animation_count = sum(item["animation"]["observed_family"] == "unresolved" for item in evidence)
    resolved_animation_ratio = round((len(events) - unknown_animation_count) / len(events), 4)
    resolved_confidence = float((resolved.get("confidence") or {}).get("score", 0.0))
    frame_coverage = float((resolved.get("confidence") or {}).get("frame_coverage_ratio", 0.0))

    return {
        "schema": "video_cloner_caption_style_grammar",
        "schema_version": 1,
        "source_reel": reel_id,
        "source_authority": "generic_flattened_video_caption_analysis",
        "source_artifacts": {"caption_style_analysis": caption_style_path.as_posix()},
        "taxonomy_policy": "small reusable families; unresolved when source evidence does not support a classification",
        "caption_style_families": families,
        "animation_families": animation_families,
        "enter_exit_combos": [{
            "combo": "unresolved->continuous_hold->unresolved",
            "caption_count": len(events),
            "relationship_counts": {"UNKNOWN": len(events)},
            "evidence_status": "UNKNOWN",
            "reason": "generic event samples do not distinguish enter from exit",
        }],
        "persistence_rules": {
            "interval_semantics": "start_inclusive_end_exclusive",
            "default_hold_behavior": "continuous_visible_interval",
            "caption_count": len(events),
            "continuous_caption_count": len(events),
            "continuous_visual_identity_event_count": sum(bool(event.get("continuous_visual_identity_id")) for event in events),
            "duration_seconds": _duration_stats(durations),
            "density_behavior": resolved_typography.get("density") or {},
            "timing_evidence_status": "OBSERVED",
            "hold_behavior_status": "INFERRED",
        },
        "font_rules": {
            "font_family_candidates": _counts(fonts),
            "font_style_candidates": _counts(styles),
            "intrinsic_weight_families": _counts(weights),
            "font_family_status": "UNKNOWN" if all(_status(font) == "UNKNOWN" for font in fonts) else "INFERRED",
            "authority_rule": "flattened-video font identity remains UNKNOWN unless the analyzer supplies a family",
        },
        "color_opacity_rules": {
            "profile_fill_colors": _counts(fills),
            "profile_stroke_presence": _counts(strokes),
            "measured_reel_median_text_color": summary.get("text_color_median"),
            "measured_reel_median_stroke_color": summary.get("stroke_color_median"),
            "measured_dark_stroke_ratio": summary.get("has_dark_stroke_ratio"),
            "fill_color_status": _status(summary.get("text_color_median"), inferred=True),
            "fill_opacity": {"value": None, "evidence_status": "UNKNOWN"},
            "opacity_rule": "UNKNOWN unless downstream source evidence supplies absolute alpha",
        },
        "layout_rules": {
            "canvas": {
                "width": (source.get("video_info") or {}).get("width"),
                "height": (source.get("video_info") or {}).get("height"),
                "orientation": "vertical" if (source.get("video_info") or {}).get("height", 0) > (source.get("video_info") or {}).get("width", 0) else "horizontal",
            },
            "dominant_position": summary.get("position") or "UNKNOWN",
            "measured_group_center_normalized": {"x": summary.get("center_x_median"), "y": summary.get("center_y_median")},
            "measured_font_height": {"px_median": summary.get("font_height_px_median"), "ratio_median": summary.get("font_height_ratio_median")},
            "rule": "retain measured per-event placement; do not force one anchor",
            "evidence_status": "INFERRED",
        },
        "per_caption_or_cluster_evidence": evidence,
        "unresolved": {
            "entry_animation_count": len(events),
            "exit_animation_count": len(events),
            "entry_source_label_count": len(events),
            "exit_source_label_count": len(events),
            "font_family_count": sum(_status((event.get("typography") or {}).get("font_family")) == "UNKNOWN" for event in events),
            "opacity_count": len(events),
            "stroke_presence_count": sum((event.get("stroke") or {}).get("enabled") is None for event in events),
            "insufficient_animation_samples_count": unknown_animation_count,
            "unsupported_families": ["type_on", "wipe_reveal", "blur_in_out", "rotate", "shake", "mask_reveal"],
        },
        "confidence": {
            "overall": round((resolved_confidence + frame_coverage + resolved_animation_ratio) / 3, 4),
            "timing_persistence": round(len(durations) / len(events), 4),
            "layout": round(resolved_confidence, 4),
            "font_weight": round(resolved_confidence, 4),
            "font_identity": 0.0 if all(_status(font) == "UNKNOWN" for font in fonts) else round(resolved_confidence, 4),
            "color": round(resolved_confidence, 4),
            "opacity": 0.0,
            "animation_family": resolved_animation_ratio,
            "enter_exit": 0.0,
            "rule": "confidence reflects generic flattened-video evidence coverage",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caption-style", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reel-id", required=True)
    args = parser.parse_args()
    grammar = build_grammar(args.caption_style, args.reel_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(grammar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(args.output), "caption_count": grammar["persistence_rules"]["caption_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
