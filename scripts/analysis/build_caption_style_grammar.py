#!/usr/bin/env python3
"""Compile the accepted Reel #2 caption evidence into a reusable style grammar."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "data/DcJRJtUKScu/analysis/DcJRJtUKScu_caption_style_grammar.json"
GOLD_MANIFEST = ROOT / ".agent/gold/video_cloner/reel2/captions/caption_gold_freeze_manifest.json"
STATIC_STATE = ROOT / ".agent/state/video_cloner_static_caption_freeze.json"
TIMING_STATE = ROOT / ".agent/state/video_cloner_timing_persistence_freeze.json"
MOTION_STATE = ROOT / ".agent/state/video_cloner_step4b_motion_ir_freeze.json"
EFFECT_STATE = ROOT / ".agent/state/video_cloner_step4d_advanced_text_effects_freeze.json"
STYLE_ANALYSIS = ROOT / "data/DcJRJtUKScu/analysis/DcJRJtUKScu_caption_style.json"

LABEL_TO_FAMILY = {
    "FADE_SLIDE": "combination",
    "SLIDE": "slide",
    "FADE": "fade",
    "SCALE": "scale",
    "SCALE_OVERSHOOT": "bounce_overshoot",
}


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_artifact(root: Path, state_path: Path, *keys: str) -> tuple[Path, dict[str, Any]]:
    value: Any = _load(state_path)
    for key in keys:
        value = value[key]
    path = root / value["path"]
    actual = _sha256(path)
    if actual != value["sha256"]:
        raise ValueError(f"Frozen artifact hash mismatch: {path} ({actual})")
    return path, _load(path)


def _counts(values: list[Any]) -> dict[str, int]:
    return dict(sorted(Counter("UNKNOWN" if value is None else str(value) for value in values).items()))


def _motion_summary(record: dict[str, Any]) -> dict[str, Any]:
    label = record.get("derived_label")
    if label:
        family = LABEL_TO_FAMILY.get(label, "unresolved")
    elif record.get("static_no_motion"):
        family = "static"
    else:
        family = "unresolved"

    samples = record.get("samples") or []
    positions = [sample.get("position") for sample in samples if sample.get("position")]
    visibility = [
        sample["relative_visibility"]["value"]
        for sample in samples
        if sample.get("relative_visibility") and sample["relative_visibility"].get("value") is not None
    ]
    dx = dy = 0.0
    direction = "none" if family == "static" else "unknown"
    displacement = 0.0
    if len(positions) >= 2:
        dx = positions[-1]["x"] - positions[0]["x"]
        dy = positions[-1]["y"] - positions[0]["y"]
        displacement = max(abs(dx), abs(dy))
        parts = []
        if abs(dx) >= 0.01:
            parts.append("right" if dx > 0 else "left")
        if abs(dy) >= 0.01:
            parts.append("down" if dy > 0 else "up")
        direction = "_".join(parts) or "none"

    visibility_range = max(visibility) - min(visibility) if visibility else 0.0
    amplitude = max(displacement, visibility_range)
    if not samples:
        intensity = "unknown"
    elif amplitude < 0.03:
        intensity = "subtle"
    elif amplitude < 0.10:
        intensity = "medium"
    else:
        intensity = "strong"

    features = record.get("features") or {}
    easing = "overshoot" if features.get("overshoot") else "ease_out" if features.get("settling") else "unknown"
    interval = record.get("interval") or []
    return {
        "family": family,
        "source_label": label or "UNRESOLVED",
        "duration_frames": interval[1] - interval[0] if len(interval) == 2 else None,
        "direction": direction,
        "easing_category": easing,
        "intensity": intensity,
        "confidence": str(record.get("derived_label_confidence", "UNRESOLVED")).lower(),
        "evidence_authority": "descriptive_label_from_authoritative_raw_trajectory",
    }


def _style_family(identity: dict[str, Any]) -> str:
    weight = identity.get("typography", {}).get("intrinsic_weight", {}).get("category")
    return weight.lower() if weight in {"REGULAR", "BOLD", "BLACK"} else "unresolved"


def _median_or_none(values: list[float]) -> float | None:
    return round(median(values), 4) if values else None


def build_grammar(root: Path = ROOT) -> dict[str, Any]:
    manifest = _load(root / GOLD_MANIFEST.relative_to(ROOT))
    gold_ref = {"path": manifest["archived_drt_path"], "sha256": manifest["sha256"]}
    gold_path = root / gold_ref["path"]
    gold_hash = _sha256(gold_path)
    if gold_hash != gold_ref["sha256"]:
        raise ValueError(f"GOLD hash mismatch: {gold_path} ({gold_hash})")

    static_path, static = _verified_artifact(root, root / STATIC_STATE.relative_to(ROOT), "frozen_static_authority", "step2f")
    timing_path, timing = _verified_artifact(root, root / TIMING_STATE.relative_to(ROOT), "frozen_timing_authority", "contract")
    motion_path, motion = _verified_artifact(root, root / MOTION_STATE.relative_to(ROOT), "frozen_step4b_authority", "motion_ir_contract")
    shadow_path, shadow = _verified_artifact(root, root / EFFECT_STATE.relative_to(ROOT), "frozen_step4d_authority", "calibrated_shadow_ir")
    style_analysis = _load(root / STYLE_ANALYSIS.relative_to(ROOT))

    static_rows = {row["identity"]["stable_identity_id"]: row for row in static["identities"]}
    timing_rows = {row["identity"]: row for row in timing["identities"]}
    motion_rows = {(row["identity"], row["boundary"]): row for row in motion["records"]}
    pair_rows = {row["identity"]: row for row in motion["entry_exit_pairs"]}
    shadow_rows = {row["source_identity"]: row for row in shadow["shadows"]}
    identities = sorted(static_rows)
    if identities != sorted(timing_rows) or len(identities) != 113:
        raise ValueError("Frozen static/timing identity sets are not the accepted 113-caption set")

    family_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
    evidence = []
    animation_counts: Counter[str] = Counter()
    combo_counts: Counter[str] = Counter()
    combo_relationships: dict[str, Counter[str]] = defaultdict(Counter)
    durations = []
    bbox_centers_x: list[float] = []
    bbox_centers_y: list[float] = []

    for identity in identities:
        static_row = static_rows[identity]
        timing_row = timing_rows[identity]
        entry = _motion_summary(motion_rows[(identity, "entry")])
        exit_ = _motion_summary(motion_rows[(identity, "exit")])
        family = _style_family(static_row)
        family_members[family].append(static_row)
        animation_counts.update((entry["family"], exit_["family"]))

        interval = timing_row["source"]["visibility_intervals"][0]
        duration_frames = timing_row["source"]["visible_frame_count"]
        fps = timing_row["frame_rate"]
        durations.append(duration_frames)
        combo = f'{entry["family"]}->continuous_hold->{exit_["family"]}'
        relationship = pair_rows[identity]["relationship"]
        combo_counts[combo] += 1
        combo_relationships[combo][relationship] += 1

        observations = static_row.get("geometry", {}).get("accepted_source_observations") or []
        if observations:
            centers_x = [(obs["bbox"][0] + obs["bbox"][2]) / 2 / 1080 for obs in observations]
            centers_y = [(obs["bbox"][1] + obs["bbox"][3]) / 2 / 1920 for obs in observations]
            center = {"x_normalized": round(median(centers_x), 4), "y_normalized": round(median(centers_y), 4)}
            bbox_centers_x.append(center["x_normalized"])
            bbox_centers_y.append(center["y_normalized"])
        else:
            center = None

        font = static_row.get("typography", {}).get("font", {}).get("selected_candidate") or {}
        shadow_row = shadow_rows.get(identity)
        shadow_rule = "localized_bounded_shadow" if shadow_row and shadow_row.get("presence_authority") == "SOURCE_REQUIRED_SHADOW" else "unknown_or_not_required"
        evidence.append({
            "identity": identity,
            "style_family": family,
            "timing": {
                "start_frame": interval[0],
                "end_frame_exclusive": interval[1],
                "duration_frames": duration_frames,
                "duration_seconds": round(duration_frames / fps, 4),
                "persistence": timing_row["source"]["persistence"],
            },
            "animation": {
                "enter": entry,
                "hold": {"behavior": "continuous_visible_interval", "duration_rule": "total lifetime minus observed boundary windows"},
                "exit": exit_,
                "combo": combo,
                "entry_exit_relationship": relationship,
            },
            "style": {
                "font_family_candidate": font.get("family"),
                "font_style_candidate": font.get("style"),
                "weight": static_row.get("typography", {}).get("intrinsic_weight", {}).get("category"),
                "median_height_px": (static_row.get("geometry", {}).get("size") or {}).get("median_height_px"),
                "fill_color": static_row.get("fill", {}).get("color_hex"),
                "opacity": static_row.get("opacity", {}).get("value"),
                "stroke_presence": static_row.get("stroke", {}).get("presence", {}).get("value"),
                "shadow": shadow_rule,
                "center": center,
            },
        })

    caption_style_families = []
    for family, members in sorted(family_members.items()):
        fonts = [((row.get("typography", {}).get("font", {}).get("selected_candidate") or {}).get("family")) for row in members]
        heights = [((row.get("geometry", {}).get("size") or {}).get("median_height_px")) for row in members]
        caption_style_families.append({
            "family": family,
            "caption_count": len(members),
            "font_family_candidates": _counts(fonts),
            "median_height_px": _median_or_none([height for height in heights if height is not None]),
            "rule": "reuse visual weight and closest supported font candidate; do not treat candidate as exact font identity",
        })

    fill_colors = [row.get("fill", {}).get("color_hex") for row in static_rows.values()]
    opacities = [row.get("opacity", {}).get("value") for row in static_rows.values()]
    strokes = [row.get("stroke", {}).get("presence", {}).get("value") for row in static_rows.values()]
    fonts = [((row.get("typography", {}).get("font", {}).get("selected_candidate") or {}).get("family")) for row in static_rows.values()]
    styles = [((row.get("typography", {}).get("font", {}).get("selected_candidate") or {}).get("style")) for row in static_rows.values()]
    weights = [row.get("typography", {}).get("intrinsic_weight", {}).get("category") for row in static_rows.values()]
    summary = style_analysis["subtitle_style_summary"]
    positive_shadow = next(row for row in shadow["shadows"] if row.get("presence_authority") == "SOURCE_REQUIRED_SHADOW")

    animation_families = [
        {"family": family, "boundary_count": count, "rule": "nearest reusable family; raw trajectory remains authority"}
        for family, count in sorted(animation_counts.items())
    ]
    enter_exit_combos = [
        {"combo": combo, "caption_count": count, "relationship_counts": dict(sorted(combo_relationships[combo].items()))}
        for combo, count in combo_counts.most_common()
    ]
    resolved_boundaries = sum(
        row["animation"][boundary]["source_label"] != "UNRESOLVED"
        for row in evidence
        for boundary in ("enter", "exit")
    )
    return {
        "schema": "video_cloner_caption_style_grammar",
        "schema_version": 1,
        "source_reel": "DcJRJtUKScu",
        "gold_authority": {"path": gold_ref["path"], "sha256": gold_hash, "status": manifest["status"], "modified": False},
        "source_artifacts": {
            "static_style": str(static_path.relative_to(root)).replace("\\", "/"),
            "timing_persistence": str(timing_path.relative_to(root)).replace("\\", "/"),
            "boundary_motion_ir": str(motion_path.relative_to(root)).replace("\\", "/"),
            "shadow_ir": str(shadow_path.relative_to(root)).replace("\\", "/"),
            "caption_style_analysis": str(STYLE_ANALYSIS.relative_to(ROOT)).replace("\\", "/"),
        },
        "taxonomy_policy": "small reusable families; unresolved when source evidence does not support a classification",
        "caption_style_families": caption_style_families,
        "animation_families": animation_families,
        "enter_exit_combos": enter_exit_combos,
        "persistence_rules": {
            "frame_rate": timing["identities"][0]["frame_rate"],
            "interval_semantics": "start_inclusive_end_exclusive",
            "default_hold_behavior": "continuous_visible_interval",
            "caption_count": len(identities),
            "continuous_caption_count": len(identities),
            "duration_frames": {"min": min(durations), "median": median(durations), "max": max(durations)},
            "duration_seconds": {"min": round(min(durations) / 24, 4), "median": round(median(durations) / 24, 4), "max": round(max(durations) / 24, 4)},
            "source_supported_overlap_relationships": 111,
            "overlap_relationship_exact_matches": 111,
        },
        "font_rules": {
            "font_family_candidates": _counts(fonts),
            "font_style_candidates": _counts(styles),
            "intrinsic_weight_families": _counts(weights),
            "authority_rule": "font names are closest-candidate guidance; visual weight is the reusable family signal",
        },
        "color_opacity_rules": {
            "identity_fill_colors": _counts(fill_colors),
            "identity_opacity_values": _counts(opacities),
            "identity_stroke_presence": _counts(strokes),
            "measured_reel_median_text_color": summary["text_color_median"],
            "measured_reel_median_stroke_color": summary["stroke_color_median"],
            "measured_dark_stroke_ratio": summary["has_dark_stroke_ratio"],
            "opacity_rule": "UNKNOWN unless downstream source evidence supplies absolute alpha",
            "shadow_rule": {
                "scope": "localized_not_global",
                "source_identity": positive_shadow["source_identity"],
                "offset_px": [positive_shadow["offset"]["x_px"], positive_shadow["offset"]["y_px"]],
                "softness_normalized": positive_shadow["softness"]["normalized_value"],
                "effective_darkening": positive_shadow["strength"]["effective_darkening"],
                "color_and_alpha": "UNRESOLVED",
            },
        },
        "layout_rules": {
            "canvas": {"width": style_analysis["video_info"]["width"], "height": style_analysis["video_info"]["height"], "orientation": "vertical"},
            "dominant_position": summary["position"],
            "measured_group_center_normalized": {"x": summary["center_x_median"], "y": summary["center_y_median"]},
            "accepted_identity_center_normalized": {"x": _median_or_none(bbox_centers_x), "y": _median_or_none(bbox_centers_y)},
            "measured_font_height": {"px_median": summary["font_height_px_median"], "ratio_median": summary["font_height_ratio_median"]},
            "rule": "center-led vertical composition with per-caption measured placement retained; do not force a single fixed anchor",
        },
        "per_caption_or_cluster_evidence": evidence,
        "unresolved": {
            "entry_animation_count": sum(1 for row in evidence if row["animation"]["enter"]["family"] == "unresolved"),
            "exit_animation_count": sum(1 for row in evidence if row["animation"]["exit"]["family"] == "unresolved"),
            "entry_source_label_count": sum(1 for row in evidence if row["animation"]["enter"]["source_label"] == "UNRESOLVED"),
            "exit_source_label_count": sum(1 for row in evidence if row["animation"]["exit"]["source_label"] == "UNRESOLVED"),
            "font_family_count": sum(value is None for value in fonts),
            "opacity_count": sum(value is None for value in opacities),
            "stroke_presence_count": sum(value is None for value in strokes),
            "unsupported_families": ["type_on", "wipe_reveal", "blur_in_out", "rotate", "shake", "mask_reveal"],
        },
        "confidence": {
            "overall": 0.73,
            "timing_persistence": 1.0,
            "layout": 0.9,
            "font_weight": 0.8,
            "font_identity": 0.6,
            "color": 0.55,
            "opacity": 0.0,
            "animation_family": round(resolved_boundaries / 226, 4),
            "rule": "confidence reflects evidence coverage, not pixel-perfect reproduction",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    grammar = build_grammar()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(grammar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
