#!/usr/bin/env python3
"""Build Major Step 3B.3C outline-vs-glow correction plan."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

VERSION = "prepare_caption_effect_mode_correction_step_3B_3C_v1_0"
EXPECTED_V3_COUNT = 116
EXPECTED_GLOW_COUNT = 99
EXPECTED_OUTLINE_COUNT = 14
EXPECTED_NONE_COUNT = 3


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


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize_hex(value: Any, fallback: str = "#000000") -> str:
    text = str(value or "").strip().lower()
    if len(text) == 4 and text.startswith("#"):
        text = "#" + "".join(ch * 2 for ch in text[1:])
    if len(text) == 7 and text.startswith("#"):
        try:
            int(text[1:], 16)
            return text
        except ValueError:
            pass
    return fallback


def rgb(hex_color: str) -> Tuple[float, float, float]:
    color = normalize_hex(hex_color)
    return tuple(int(color[i:i + 2], 16) / 255.0 for i in (1, 3, 5))  # type: ignore[return-value]


def max_rgb_delta(a: str, b: str) -> float:
    return max(abs(x - y) for x, y in zip(rgb(a), rgb(b)))


def parse_source(item: Dict[str, Any]) -> Dict[str, Any]:
    resolution = item.get("profile_resolution") or {}
    details = resolution.get("details") or {}
    event = details.get("event") if isinstance(details, dict) else None
    group = details.get("group") if isinstance(details, dict) else None

    if isinstance(event, dict):
        typography = event.get("typography") or {}
        stroke = event.get("stroke") or {}
        shadow = event.get("shadow") or {}
        font_height = finite(typography.get("font_height_px"))
        stroke_enabled = bool(stroke.get("enabled"))
        shadow_enabled = bool(shadow.get("enabled"))
        stroke_width = finite(stroke.get("width_px_estimate"), 0.0) or 0.0
        shadow_blur = finite(shadow.get("blur_px_estimate"), 0.0) or 0.0
        shadow_opacity = clamp(finite(shadow.get("opacity_estimate"), 0.85) or 0.0, 0.0, 1.0)
        stroke_color = normalize_hex(stroke.get("color"))
        shadow_color = normalize_hex(shadow.get("color"))
        source_detail_id = event.get("event_id")
        confidence = (event.get("confidence") or {}).get("score")
        source_kind = "caption_style_event"
    elif isinstance(group, dict):
        font_height = finite(group.get("estimated_font_height_px"))
        stroke_enabled = bool(group.get("has_dark_stroke"))
        shadow_enabled = bool(group.get("has_shadow"))
        stroke_width = 3.0 if stroke_enabled else 0.0
        shadow_blur = 2.0 if shadow_enabled else 0.0
        shadow_opacity = 0.85 if shadow_enabled else 0.0
        stroke_color = normalize_hex(group.get("estimated_stroke_color"))
        shadow_color = normalize_hex(group.get("estimated_shadow_color"))
        source_detail_id = group.get("frame_index")
        confidence = group.get("confidence")
        source_kind = "classified_caption_group"
    else:
        raise ValueError(f"No source style metadata for {item.get('name')}")

    if font_height is None or font_height <= 0:
        raise ValueError(f"Invalid font height for {item.get('name')}")

    outline_ratio = clamp(stroke_width / font_height, 0.0, 0.50) if stroke_enabled else 0.0
    shadow_softness = clamp(shadow_blur / font_height, 0.0, 0.50) if shadow_enabled else 0.0
    color_delta = max_rgb_delta(stroke_color, shadow_color)

    # Conservative reclassification: when the detector reports a narrow dark edge and
    # a blurred shadow using effectively the same color, but has no directional-offset
    # evidence, the dark perimeter is much more likely a centered halo/glow than a true
    # stroked outline. Distinct stroke/shadow colors remain outline+shadow.
    glow_evidence = bool(
        stroke_enabled
        and shadow_enabled
        and color_delta <= 0.08
        and shadow_blur > 0.0
        and outline_ratio <= 0.10
    )

    if glow_evidence:
        mode = "shadow_glow_only"
    elif stroke_enabled and shadow_enabled:
        mode = "outline_and_shadow"
    elif shadow_enabled:
        mode = "shadow_only"
    elif stroke_enabled:
        mode = "outline_only"
    else:
        mode = "none"

    glow_softness = clamp(max(shadow_softness, outline_ratio * 0.60), 0.0, 0.12)
    glow_opacity = clamp(min(shadow_opacity if shadow_opacity > 0 else 0.65, 0.65), 0.0, 1.0)

    return {
        "style_profile_id": str(resolution.get("style_profile_id") or ""),
        "source": source_kind,
        "source_detail_id": source_detail_id,
        "confidence": confidence,
        "font_height_px": round(font_height, 8),
        "classification": {
            "mode": mode,
            "reason": (
                "same_or_near_same_stroke_shadow_color_plus_blur_without_directional_offset"
                if mode == "shadow_glow_only"
                else "retain_source_effect_separation"
            ),
            "stroke_shadow_color_delta": round(color_delta, 8),
            "outline_ratio": round(outline_ratio, 10),
            "shadow_blur_px": round(shadow_blur, 8),
            "directional_offset_evidence": False,
        },
        "target": {
            "outline": {
                "enabled": mode in {"outline_and_shadow", "outline_only"},
                "color": stroke_color,
                "thickness": round(outline_ratio, 10),
                "outside_only": 1.0,
            },
            "shadow": {
                "enabled": mode in {"shadow_glow_only", "outline_and_shadow", "shadow_only"},
                "render_mode": "centered_glow" if mode == "shadow_glow_only" else "directional_shadow",
                "color": shadow_color,
                "opacity": round(glow_opacity if mode == "shadow_glow_only" else shadow_opacity, 8),
                "offset": [0.0, 0.0] if mode == "shadow_glow_only" else [0.003, 0.003],
                "softness": round(glow_softness if mode == "shadow_glow_only" else shadow_softness, 10),
            },
        },
        "source_measurements": {
            "stroke_enabled": stroke_enabled,
            "stroke_color": stroke_color,
            "stroke_width_px": round(stroke_width, 8),
            "shadow_enabled": shadow_enabled,
            "shadow_color": shadow_color,
            "shadow_blur_px": round(shadow_blur, 8),
            "shadow_opacity": round(shadow_opacity, 8),
        },
    }


def validate_gate(payload: Dict[str, Any], step: str, mode: str) -> List[str]:
    failures: List[str] = []
    if not payload.get("ok"):
        failures.append(f"{step}_not_ok")
    if payload.get("mode") != mode and payload.get("run_mode") != mode:
        failures.append(f"{step}_wrong_mode")
    if payload.get("failures"):
        failures.append(f"{step}_has_failures")
    return failures


def build(args: argparse.Namespace) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    font_path = Path(args.font_report).resolve()
    step3c_path = Path(args.step_3c_report).resolve()
    step3b3b_validation_path = Path(args.step_3b3b_idempotency_validation).resolve()
    step3b4a_validation_path = Path(args.step_3b4a_idempotency_validation).resolve()

    font = load_json(font_path)
    step3c = load_json(step3c_path)
    step3b3b_validation = load_json(step3b3b_validation_path)
    step3b4a_validation = load_json(step3b4a_validation_path)

    failures: List[str] = []
    warnings: List[str] = [
        "The classifier is intentionally conservative: only same/near-same stroke+shadow evidence is converted to centered glow. Distinct effect colors retain outline+shadow."
    ]
    if not font.get("ok") or int(font.get("v3_candidate_count") or 0) != args.expected_v3_count:
        failures.append("font_report_gate_failed")
    failures.extend(validate_gate(step3c, "step_3C", "idempotent_second_run"))
    failures.extend(validate_gate(step3b3b_validation, "step_3B_3B", "idempotent_second_run"))
    failures.extend(validate_gate(step3b4a_validation, "step_3B_4A", "idempotent_second_run"))

    step3c_items = {
        str(row.get("cue_id")): row
        for row in (step3c.get("items") or [])
        if isinstance(row, dict) and row.get("cue_id")
    }

    items: List[Dict[str, Any]] = []
    seen_names, seen_cues = set(), set()
    for row in font.get("items") or []:
        if not isinstance(row, dict):
            failures.append("non_object_font_item")
            continue
        name = str(row.get("name") or "")
        cue_id = str(row.get("cue_id") or "")
        if not name or not cue_id or name in seen_names or cue_id in seen_cues:
            failures.append(f"invalid_or_duplicate_item:{name}:{cue_id}")
            continue
        seen_names.add(name)
        seen_cues.add(cue_id)
        try:
            effect = parse_source(row)
        except Exception as exc:
            failures.append(f"source_parse_failed:{name}:{type(exc).__name__}:{exc}")
            continue
        targets = []
        for target in (step3c_items.get(cue_id) or {}).get("targets") or []:
            if isinstance(target, dict):
                targets.append({
                    "input": target.get("input"),
                    "local_frame": int(target.get("local_frame") or 0),
                    "expected": target.get("expected"),
                })
        items.append({
            "name": name,
            "cue_id": cue_id,
            "cue_index": int(row.get("cue_index") or row.get("cue_number") or 0),
            "start": int(row.get("start") or 0),
            "end": int(row.get("end") or 0),
            "text": str(row.get("rendered_text") or ""),
            "expected_font_family": str(row.get("font_after") or row.get("requested_family") or ""),
            "expected_font_face": str(row.get("style_after") or row.get("requested_face") or ""),
            "style_profile_id": effect["style_profile_id"],
            "effect": effect,
            "protected_animation_targets": targets,
        })

    items.sort(key=lambda row: (row["cue_index"], row["name"]))
    counts: Dict[str, int] = {}
    for item in items:
        mode = item["effect"]["classification"]["mode"]
        counts[mode] = counts.get(mode, 0) + 1
    animation_target_count = sum(len(row["protected_animation_targets"]) for row in items)

    expected_counts = {
        "shadow_glow_only": args.expected_glow_count,
        "outline_and_shadow": args.expected_outline_count,
        "none": args.expected_none_count,
    }
    for mode, expected in expected_counts.items():
        if counts.get(mode, 0) != expected:
            failures.append(f"classification_count_mismatch:{mode}:{counts.get(mode, 0)}:{expected}")
    unexpected_modes = set(counts) - set(expected_counts)
    if unexpected_modes:
        failures.append("unexpected_modes:" + ",".join(sorted(unexpected_modes)))
    if len(items) != args.expected_v3_count:
        failures.append("v3_item_count_mismatch")
    if animation_target_count != 16:
        failures.append("animation_target_count_mismatch")

    plan: Dict[str, Any] = {
        "ok": not failures,
        "schema": "video_cloner_caption_effect_mode_correction_plan",
        "schema_version": "1.0",
        "step": "Major Step 3B.3C",
        "planner_version": VERSION,
        "created_at_unix": round(time.time(), 6),
        "expected_v3_count": args.expected_v3_count,
        "outline_element": 2,
        "shadow_element": 3,
        "classifier": {
            "name": "same_color_blurred_edge_without_directional_offset",
            "max_stroke_shadow_rgb_delta": 0.08,
            "max_outline_ratio_for_glow": 0.10,
            "glow_opacity_cap": 0.65,
            "glow_softness_from": "max(shadow_blur/font_height, 0.60*stroke_width/font_height)",
            "glow_offset": [0.0, 0.0],
        },
        "inputs": {
            "font_report": str(font_path),
            "step_3c_idempotency_report": str(step3c_path),
            "step_3B_3B_idempotency_validation": str(step3b3b_validation_path),
            "step_3B_4A_idempotency_validation": str(step3b4a_validation_path),
        },
        "summary": {
            "v3_item_count": len(items),
            "glow_target_count": counts.get("shadow_glow_only", 0),
            "retained_outline_count": counts.get("outline_and_shadow", 0),
            "no_effect_count": counts.get("none", 0),
            "protected_animation_target_count": animation_target_count,
        },
        "items": items,
        "warnings": warnings,
        "failures": failures,
    }
    plan["plan_hash"] = canonical_hash(plan)

    checks = {
        "font_report_gate": "font_report_gate_failed" not in failures,
        "step_3C_gate": not any(row.startswith("step_3C") for row in failures),
        "step_3B_3B_gate": not any(row.startswith("step_3B_3B") for row in failures),
        "step_3B_4A_gate": not any(row.startswith("step_3B_4A") for row in failures),
        "v3_item_count": len(items) == args.expected_v3_count,
        "unique_names": len(seen_names) == args.expected_v3_count,
        "unique_cues": len(seen_cues) == args.expected_v3_count,
        "glow_target_count": counts.get("shadow_glow_only", 0) == args.expected_glow_count,
        "retained_outline_count": counts.get("outline_and_shadow", 0) == args.expected_outline_count,
        "no_effect_count": counts.get("none", 0) == args.expected_none_count,
        "protected_animation_target_count": animation_target_count == 16,
        "plan_ok": not failures,
    }
    validation = {
        "ok": all(checks.values()) and not failures,
        "step": "Major Step 3B.3C",
        "validator_version": VERSION,
        "plan": str(Path(args.output_plan).resolve()),
        "plan_hash": plan["plan_hash"],
        "checks": checks,
        "summary": plan["summary"],
        "warnings": warnings,
        "failures": failures + [f"check_failed:{key}" for key, ok in checks.items() if not ok],
    }
    return plan, validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--font-report", required=True)
    parser.add_argument("--step-3c-report", required=True)
    parser.add_argument("--step-3b3b-idempotency-validation", required=True)
    parser.add_argument("--step-3b4a-idempotency-validation", required=True)
    parser.add_argument("--output-plan", required=True)
    parser.add_argument("--output-validation", required=True)
    parser.add_argument("--expected-v3-count", type=int, default=EXPECTED_V3_COUNT)
    parser.add_argument("--expected-glow-count", type=int, default=EXPECTED_GLOW_COUNT)
    parser.add_argument("--expected-outline-count", type=int, default=EXPECTED_OUTLINE_COUNT)
    parser.add_argument("--expected-none-count", type=int, default=EXPECTED_NONE_COUNT)
    args = parser.parse_args()
    try:
        plan, validation = build(args)
    except Exception as exc:
        validation = {"ok": False, "step": "Major Step 3B.3C", "validator_version": VERSION, "failures": [f"{type(exc).__name__}: {exc}"]}
        write_json(Path(args.output_validation), validation)
        print(json.dumps(validation, indent=2))
        return 1
    write_json(Path(args.output_plan), plan)
    write_json(Path(args.output_validation), validation)
    print(json.dumps(validation, indent=2))
    return 0 if validation.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
