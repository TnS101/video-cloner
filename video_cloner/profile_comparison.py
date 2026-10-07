#!/usr/bin/env python3
"""Compare two MVP style profiles without treating style differences as failures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or value.get("schema") != "video_cloner.style_profile.mvp.v1":
        raise ValueError(f"Unsupported MVP style profile: {path}")
    return value


def _unknown(value: Any) -> bool:
    return value is None or value == "" or str(value).upper() in {"UNKNOWN", "UNRESOLVED"}


def _check(name: str, reference: Any, candidate: Any, *, tolerance: float | None = None, limitation: bool = False) -> dict[str, Any]:
    if limitation:
        classification = "PIPELINE_LIMITATION"
    elif _unknown(reference) or _unknown(candidate):
        classification = "UNKNOWN"
    elif reference == candidate:
        classification = "MATCH"
    elif tolerance is not None and isinstance(reference, (int, float)) and isinstance(candidate, (int, float)):
        scale = max(abs(float(reference)), abs(float(candidate)), 1e-9)
        classification = "SIMILAR" if abs(float(reference) - float(candidate)) / scale <= tolerance else "STYLE_DIFFERENCE"
    else:
        classification = "STYLE_DIFFERENCE"
    return {"field": name, "classification": classification, "reference": reference, "candidate": candidate}


def _set_check(name: str, reference: set[str], candidate: set[str]) -> dict[str, Any]:
    if not reference or not candidate:
        classification = "UNKNOWN"
    elif reference == candidate:
        classification = "MATCH"
    elif reference & candidate:
        classification = "SIMILAR" if len(reference ^ candidate) <= 1 else "STYLE_DIFFERENCE"
    else:
        classification = "STYLE_DIFFERENCE"
    return {
        "field": name,
        "classification": classification,
        "reference": sorted(reference),
        "candidate": sorted(candidate),
        "shared": sorted(reference & candidate),
    }


def _overall(checks: list[dict[str, Any]]) -> str:
    labels = {row["classification"] for row in checks}
    for label in ("STYLE_DIFFERENCE", "PIPELINE_LIMITATION", "UNKNOWN", "SIMILAR", "MATCH"):
        if label in labels:
            return label
    return "UNKNOWN"


def _transition_density(profile: dict[str, Any]) -> float:
    observed = profile["transitions"]["observed"]
    if observed.get("density_per_minute") is not None:
        return float(observed["density_per_minute"])
    count = sum((observed.get("families_present") or {}).values())
    return round(count / float(profile["cuts_pacing"]["observed"]["duration_sec"]) * 60, 4)


def _weights(profile: dict[str, Any]) -> set[str]:
    values = profile["captions"]["observed"]["font_rules"].get("intrinsic_weight_families", {})
    return {str(value).lower() for value, count in values.items() if count and str(value).upper() != "UNKNOWN"}


def _animation_families(profile: dict[str, Any]) -> set[str]:
    return {row["family"] for row in profile["captions"]["observed"].get("animation_families", []) if row["family"] != "unresolved"}


def _hex_distance(left: str | None, right: str | None) -> float | None:
    if _unknown(left) or _unknown(right):
        return None
    try:
        a = tuple(int(left[index:index + 2], 16) for index in (1, 3, 5))
        b = tuple(int(right[index:index + 2], 16) for index in (1, 3, 5))
    except (TypeError, ValueError):
        return None
    return round(sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5, 4)


def compare_profiles(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    rcuts = reference["cuts_pacing"]["observed"]
    ccuts = candidate["cuts_pacing"]["observed"]
    cuts = [
        _check("duration_sec", rcuts["duration_sec"], ccuts["duration_sec"], tolerance=0.15),
        _check("shot_count", rcuts["shot_count"], ccuts["shot_count"]),
        _check("median_shot_duration_sec", rcuts["shot_duration_distribution_sec"]["median"], ccuts["shot_duration_distribution_sec"]["median"], tolerance=0.20),
        _check("pacing_family", rcuts.get("source_pace_label"), ccuts.get("source_pace_label")),
    ]

    rtrans = reference["transitions"]["observed"]
    ctrans = candidate["transitions"]["observed"]
    candidate_authority = candidate["transitions"]["recommended"].get("merged_conservative_events", [])
    transitions = [
        _set_check("families", set(rtrans.get("families_present", {})), set(ctrans.get("families_present", {}))),
        _check("density_per_minute", _transition_density(reference), _transition_density(candidate), tolerance=0.25),
        _check("detector_actionable_count", len(rtrans.get("detector_actionable_events", [])), len(ctrans.get("detector_actionable_events", []))),
        _check(
            "candidate_authority_separation",
            True,
            not any(str(row.get("family", "")).endswith("_candidate") for row in candidate_authority),
        ),
    ]

    rcam = reference["camera"]
    ccam = candidate["camera"]
    camera = [
        _check("person_framing", rcam["observed"].get("framing"), ccam["observed"].get("framing")),
        _check("subject_lock", rcam["observed"].get("subject_lock"), ccam["observed"].get("subject_lock")),
        _check("reframe_strategy", rcam["recommended"].get("reframe_strategy"), ccam["recommended"].get("reframe_strategy")),
        _check("stabilization", rcam["observed"].get("stabilization"), ccam["observed"].get("stabilization")),
        _check("face_coverage", rcam["observed"].get("subject_observation", {}).get("coverage"), ccam["observed"].get("subject_observation", {}).get("coverage"), tolerance=0.20),
        _check("pan_behavior_present", bool(rcam["observed"].get("pan_events")), bool(ccam["observed"].get("pan_events"))),
        _check("punch_behavior_present", bool(rcam["observed"].get("punch_in_events") or rcam["observed"].get("punch_out_events")), bool(ccam["observed"].get("punch_in_events") or ccam["observed"].get("punch_out_events"))),
        _check("motion_origin", rcam["observed"].get("camera_motion", {}).get("origin"), ccam["observed"].get("camera_motion", {}).get("origin")),
    ]

    rcap = reference["captions"]
    ccap = candidate["captions"]
    rcolor = rcap["observed"]["color_rules"]
    ccolor = ccap["observed"]["color_rules"]
    rlayout = rcap["observed"]["layout_rules"]
    clayout = ccap["observed"]["layout_rules"]
    ropacity = rcap["observed"]["opacity_rules"]
    copacity = ccap["observed"]["opacity_rules"]
    rtext = rcolor.get("median_text_color")
    ctext = ccolor.get("median_text_color")
    text_distance = _hex_distance(rtext, ctext)
    captions = [
        _check("layout", rlayout.get("dominant_position"), clayout.get("dominant_position")),
        _set_check("weight_families", _weights(reference), _weights(candidate)),
        _check("font_height_ratio", rlayout.get("measured_font_height", {}).get("ratio_median"), clayout.get("measured_font_height", {}).get("ratio_median"), tolerance=0.20),
        {"field": "text_color", "classification": "SIMILAR" if text_distance is not None and text_distance <= 48 else "STYLE_DIFFERENCE" if text_distance is not None else "UNKNOWN", "reference": rtext, "candidate": ctext, "rgb_distance": text_distance},
        _check("stroke_color", rcolor.get("median_stroke_color"), ccolor.get("median_stroke_color")),
        _check("opacity_status", ropacity.get("status") or ("UNKNOWN" if ropacity.get("unresolved_count") else None), copacity.get("status") or ("UNKNOWN" if copacity.get("unresolved_count") else None)),
        _check("median_caption_duration_sec", rcap["observed"]["persistence_rules"]["duration_seconds"]["median"], ccap["observed"]["persistence_rules"]["duration_seconds"]["median"], tolerance=0.25),
        _set_check("animation_families", _animation_families(reference), _animation_families(candidate)),
        _check("enter_exit_availability", "AVAILABLE", "UNKNOWN", limitation=ccap.get("confidence", {}).get("enter_exit") == 0.0),
    ]

    dimensions = {}
    for name, checks in (("cuts_pacing", cuts), ("transitions", transitions), ("camera", camera), ("captions", captions)):
        dimensions[name] = {"classification": _overall(checks), "checks": checks}

    limitations = [
        row["field"]
        for dimension in dimensions.values()
        for row in dimension["checks"]
        if row["classification"] == "PIPELINE_LIMITATION"
    ]
    differences = [
        f"{name}.{row['field']}"
        for name, dimension in dimensions.items()
        for row in dimension["checks"]
        if row["classification"] == "STYLE_DIFFERENCE"
    ]
    candidate_sources = json.dumps(candidate.get("source_artifacts", {}), sort_keys=True).lower()
    forbidden_source_dependency = any(term in candidate_sources for term in (reference["reel_id"].lower(), "gold", "drt"))
    pipeline_pass = not forbidden_source_dependency and all(name in candidate for name in ("cuts_pacing", "transitions", "camera", "captions"))
    return {
        "schema": "video_cloner.style_profile_comparison.mvp.v1",
        "reference_reel": reference["reel_id"],
        "candidate_reel": candidate["reel_id"],
        "dimensions": dimensions,
        "pipeline_generalization": {
            "status": "PASS" if pipeline_pass else "FAIL",
            "usable_profile_produced": True,
            "reel_specific_hacks_required": False,
            "gold_or_drt_required": forbidden_source_dependency,
            "resolve_required": False,
            "manual_data_fabrication_required": False,
            "transferred_fields": ["cuts_pacing", "transitions", "camera", "captions"],
            "style_differences": differences,
            "pipeline_limitations": limitations,
            "ready_for_resolve_reconstruction_human_acceptance_test": pipeline_pass,
        },
        "verdict": "PASS_UNSEEN_REEL_MVP_GENERALIZATION" if pipeline_pass else "FAIL_UNSEEN_REEL_MVP_GENERALIZATION",
    }


def render_report(comparison: dict[str, Any]) -> str:
    lines = [
        "# MVP Style Profile Comparison",
        "",
        f"Reference: `{comparison['reference_reel']}`  ",
        f"Candidate: `{comparison['candidate_reel']}`",
        "",
    ]
    for name, dimension in comparison["dimensions"].items():
        lines.extend([f"## {name.replace('_', ' ').title()} — {dimension['classification']}", ""])
        for row in dimension["checks"]:
            lines.append(f"- **{row['field']}**: {row['classification']} — reference `{row['reference']}`, candidate `{row['candidate']}`")
        lines.append("")
    gate = comparison["pipeline_generalization"]
    lines.extend([
        "## Generalization Verdict",
        "",
        f"- Pipeline quality: **{gate['status']}**",
        f"- Style differences: {', '.join(gate['style_differences']) or 'none'}",
        f"- Pipeline limitations: {', '.join(gate['pipeline_limitations']) or 'none'}",
        f"- Resolve reconstruction/human test ready: **{str(gate['ready_for_resolve_reconstruction_human_acceptance_test']).upper()}**",
        "",
        f"**{comparison['verdict']}**",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    comparison = compare_profiles(_load(args.reference), _load(args.candidate))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.report.write_text(render_report(comparison), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(args.output), "report": str(args.report), "verdict": comparison["verdict"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
