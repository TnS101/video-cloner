#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

VERSION = "prepare_caption_outline_shadow_step_3B_3B_v1_0_full_rollout_plan"
EXPECTED_V3_COUNT = 116


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temp.replace(path)


def finite(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


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


def canonical_hash(payload: Dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("plan_hash", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def median_or_none(values: Iterable[Optional[float]]) -> Optional[float]:
    rows = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return statistics.median(rows) if rows else None


def color_luminance(hex_color: str) -> float:
    color = normalize_hex(hex_color)
    channels = [int(color[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def robust_profile_color(colors: Sequence[str], fallback: str = "#000000") -> str:
    cleaned = [normalize_hex(color, fallback) for color in colors]
    if not cleaned:
        return fallback
    # Prefer the most common exact color. Ties prefer the darker value because the
    # upstream detector identifies dark stroke/shadow components more reliably than hue.
    counts = Counter(cleaned)
    return sorted(counts, key=lambda color: (-counts[color], color_luminance(color), color))[0]


def extract_effect_source(item: Dict[str, Any]) -> Dict[str, Any]:
    resolution = item.get("profile_resolution") or {}
    details = resolution.get("details") or {}
    event = details.get("event") if isinstance(details, dict) else None
    group = details.get("group") if isinstance(details, dict) else None

    source = str(resolution.get("source") or "unknown")
    profile_id = str(resolution.get("style_profile_id") or "")
    font_height_px: Optional[float] = None
    stroke_enabled = False
    stroke_color = "#000000"
    stroke_width_px = 0.0
    shadow_enabled = False
    shadow_color = "#000000"
    shadow_opacity = 0.0
    shadow_blur_px = 0.0
    source_detail_id = None

    if isinstance(event, dict):
        source_detail_id = event.get("event_id")
        typography = event.get("typography") or {}
        stroke = event.get("stroke") or {}
        shadow = event.get("shadow") or {}
        font_height_px = finite(typography.get("font_height_px"))
        stroke_enabled = bool(stroke.get("enabled"))
        stroke_color = normalize_hex(stroke.get("color"))
        stroke_width_px = finite(stroke.get("width_px_estimate"), 0.0) or 0.0
        shadow_enabled = bool(shadow.get("enabled"))
        shadow_color = normalize_hex(shadow.get("color"))
        shadow_opacity = clamp(finite(shadow.get("opacity_estimate"), 0.85) or 0.0, 0.0, 1.0)
        shadow_blur_px = finite(shadow.get("blur_px_estimate"), 0.0) or 0.0
    elif isinstance(group, dict):
        source_detail_id = group.get("frame_index")
        font_height_px = finite(group.get("estimated_font_height_px"))
        stroke_enabled = bool(group.get("has_dark_stroke"))
        stroke_color = normalize_hex(group.get("estimated_stroke_color"))
        stroke_width_px = 3.0 if stroke_enabled else 0.0
        shadow_enabled = bool(group.get("has_shadow"))
        shadow_color = normalize_hex(group.get("estimated_shadow_color"))
        shadow_opacity = 0.85 if shadow_enabled else 0.0
        shadow_blur_px = 2.0 if shadow_enabled else 0.0

    if font_height_px is None or font_height_px <= 0:
        raise ValueError(f"Missing/invalid font height for {item.get('name')}")

    outline_thickness = 0.0
    if stroke_enabled and stroke_width_px > 0:
        outline_thickness = clamp(stroke_width_px / font_height_px, 0.001, 0.50)

    # Upstream metadata currently has blur but not directional shadow offset.
    # Keep the offset explicit and conservative instead of pretending it was detected.
    shadow_offset = [0.003, 0.003]
    shadow_softness = 0.0
    if shadow_enabled and shadow_blur_px > 0:
        shadow_softness = clamp(shadow_blur_px / font_height_px, 0.0, 0.50)

    return {
        "style_profile_id": profile_id,
        "source": source,
        "source_detail_id": source_detail_id,
        "font_height_px": round(font_height_px, 8),
        "outline": {
            "enabled": stroke_enabled,
            "color": stroke_color,
            "stroke_width_px": round(stroke_width_px, 8),
            "thickness": round(outline_thickness, 10),
            "thickness_source": "stroke_width_px_div_font_height_px",
        },
        "shadow": {
            "enabled": shadow_enabled,
            "color": shadow_color,
            "opacity": round(shadow_opacity, 8),
            "blur_px": round(shadow_blur_px, 8),
            "softness": round(shadow_softness, 10),
            "softness_source": "blur_px_div_font_height_px",
            "offset": shadow_offset,
            "offset_source": "conservative_default_missing_upstream_offset",
        },
    }


def validate_step_3c_gate(report: Dict[str, Any]) -> List[str]:
    failures: List[str] = []
    summary = report.get("summary") or {}
    if not report.get("ok"):
        failures.append("step_3C_report_ok_false")
    if report.get("run_mode") != "idempotent_second_run":
        failures.append("step_3C_not_idempotent_second_run")
    expected = {
        "v3_candidate_count": 116,
        "selected_animation_count": 8,
        "mapped_count": 8,
        "modified_count": 0,
        "already_correct_count": 8,
        "target_keyframe_count": 16,
        "readback_success_count": 8,
        "readback_keyframe_count": 16,
        "failed_count": 0,
        "font_integrity_failure_count": 0,
        "timeline_integrity_failure_count": 0,
    }
    for key, value in expected.items():
        if int(summary.get(key) or 0) != value:
            failures.append(f"step_3C_summary_mismatch:{key}")
    if not summary.get("keyframe_presence_verified"):
        failures.append("step_3C_keyframe_presence_not_verified")
    if not (report.get("core_track_integrity") or {}).get("ok"):
        failures.append("step_3C_core_track_integrity_false")
    if not (report.get("v3_track_integrity") or {}).get("ok"):
        failures.append("step_3C_v3_track_integrity_false")
    return failures


def validate_probe_gate(validation: Dict[str, Any]) -> List[str]:
    failures: List[str] = []
    summary = validation.get("summary") or {}
    checks = validation.get("checks") or {}
    if not validation.get("ok"):
        failures.append("step_3B_3A_validation_ok_false")
    if validation.get("mode") != "idempotent_second_run":
        failures.append("step_3B_3A_not_idempotent_second_run")
    expected = {
        "v3_candidate_count": 116,
        "plan_item_count": 116,
        "probe_item_count": 1,
        "mapped_count": 1,
        "modified_count": 0,
        "already_correct_count": 1,
        "outline_requested_count": 1,
        "outline_verified_count": 1,
        "shadow_requested_count": 1,
        "shadow_verified_count": 1,
        "required_input_count": 14,
        "verified_required_input_count": 14,
        "optional_input_count": 3,
        "verified_optional_input_count": 3,
        "protected_animation_target_count": 2,
        "protected_animation_verified_count": 2,
        "failed_count": 0,
    }
    for key, value in expected.items():
        if int(summary.get(key) or 0) != value:
            failures.append(f"step_3B_3A_summary_mismatch:{key}")
    required_checks = (
        "report_ok", "persistent_readback", "protected_integrity",
        "track_integrity", "v3_track_integrity", "no_report_failures",
        "second_run_modified_count", "second_run_already_correct_count",
    )
    for key in required_checks:
        if not checks.get(key):
            failures.append(f"step_3B_3A_check_false:{key}")
    if validation.get("failures"):
        failures.append("step_3B_3A_validation_has_failures")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Major Step 3B.3B full V3 outline/shadow rollout plan.")
    parser.add_argument("--font-report", required=True)
    parser.add_argument("--step-3c-report", required=True)
    parser.add_argument("--probe-idempotency-validation", required=True)
    parser.add_argument("--output-plan", required=True)
    parser.add_argument("--output-validation", required=True)
    parser.add_argument("--expected-v3-count", type=int, default=EXPECTED_V3_COUNT)
    parser.add_argument("--expected-rollout-target-count", type=int, default=113)
    parser.add_argument("--accepted-probe-cue-id", default="sub_019")
    args = parser.parse_args()

    font_report_path = Path(args.font_report)
    step_3c_report_path = Path(args.step_3c_report)
    probe_validation_path = Path(args.probe_idempotency_validation)
    output_plan = Path(args.output_plan)
    output_validation = Path(args.output_validation)
    expected = int(args.expected_v3_count)
    expected_targets = int(args.expected_rollout_target_count)

    failures: List[str] = []
    warnings: List[str] = [
        "Known visual debt: Step 3B.3B preserves the current V3 fill color. White-vs-dark-gray fill fidelity is deferred."
    ]
    font_report = load_json(font_report_path)
    step_3c_report = load_json(step_3c_report_path)
    probe_validation = load_json(probe_validation_path)

    if not font_report.get("ok"):
        failures.append("font_report_ok_false")
    if int(font_report.get("v3_candidate_count") or 0) != expected:
        failures.append("font_report_v3_candidate_count_mismatch")
    if int(font_report.get("mapped_count") or 0) != expected:
        failures.append("font_report_mapped_count_mismatch")
    if int(font_report.get("readback_success_count") or 0) != expected:
        failures.append("font_report_readback_count_mismatch")
    failures.extend(validate_step_3c_gate(step_3c_report))
    failures.extend(validate_probe_gate(probe_validation))

    source_items = font_report.get("items") or []
    if len(source_items) != expected:
        failures.append("font_report_item_count_mismatch")

    step_3c_items = {
        str(row.get("cue_id")): row
        for row in (step_3c_report.get("items") or [])
        if isinstance(row, dict) and row.get("cue_id")
    }

    items: List[Dict[str, Any]] = []
    seen_names = set()
    seen_cues = set()
    profile_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for row in source_items:
        if not isinstance(row, dict):
            failures.append("non_object_font_report_item")
            continue
        name = str(row.get("name") or "")
        cue_id = str(row.get("cue_id") or "")
        if not name or not cue_id:
            failures.append("item_missing_name_or_cue")
            continue
        if name in seen_names or cue_id in seen_cues:
            failures.append(f"duplicate_item:{name}:{cue_id}")
            continue
        seen_names.add(name)
        seen_cues.add(cue_id)
        try:
            source_effect = extract_effect_source(row)
        except Exception as exc:
            failures.append(f"source_effect_error:{name}:{type(exc).__name__}:{exc}")
            continue

        protected_animation_targets: List[Dict[str, Any]] = []
        step_3c_item = step_3c_items.get(cue_id)
        if step_3c_item:
            for target in step_3c_item.get("targets") or []:
                protected_animation_targets.append({
                    "input": target.get("input"),
                    "local_frame": target.get("local_frame"),
                    "expected": target.get("expected"),
                })

        rollout_selected = bool(
            source_effect["outline"]["enabled"] or source_effect["shadow"]["enabled"]
        )
        item = {
            "name": name,
            "cue_id": cue_id,
            "cue_index": int(row.get("cue_index") or row.get("cue_number") or 0),
            "start": int(row.get("start") or 0),
            "end": int(row.get("end") or 0),
            "text": str(row.get("rendered_text") or ""),
            "expected_font_family": str(row.get("font_after") or row.get("requested_family") or ""),
            "expected_font_face": str(row.get("style_after") or row.get("requested_face") or ""),
            "style_profile_id": source_effect["style_profile_id"],
            "source_effect": source_effect,
            "protected_animation_targets": protected_animation_targets,
            "rollout_selected": rollout_selected,
            "accepted_probe": cue_id == str(args.accepted_probe_cue_id),
        }
        items.append(item)
        profile_rows[source_effect["style_profile_id"]].append(source_effect)

    items.sort(key=lambda row: (row["cue_index"], row["name"]))
    targets = [row for row in items if row["rollout_selected"]]
    disabled = [row for row in items if not row["rollout_selected"]]
    accepted_probe = [row for row in items if row["accepted_probe"]]
    if len(targets) != expected_targets:
        failures.append(f"rollout_target_count_mismatch:{len(targets)}")
    if len(accepted_probe) != 1:
        failures.append("accepted_probe_not_unique")
    elif not accepted_probe[0]["rollout_selected"]:
        failures.append("accepted_probe_not_rollout_selected")
    if sum(len(row["protected_animation_targets"]) for row in items) != 16:
        failures.append("protected_animation_target_total_mismatch")

    profile_calibration: Dict[str, Any] = {}
    for profile_id, rows in sorted(profile_rows.items()):
        outline_active = [row for row in rows if row["outline"]["enabled"]]
        shadow_active = [row for row in rows if row["shadow"]["enabled"]]
        profile_calibration[profile_id] = {
            "item_count": len(rows),
            "outline_enabled_count": len(outline_active),
            "shadow_enabled_count": len(shadow_active),
            "median_outline_thickness": median_or_none(row["outline"]["thickness"] for row in outline_active),
            "representative_outline_color": robust_profile_color([row["outline"]["color"] for row in outline_active]),
            "median_shadow_opacity": median_or_none(row["shadow"]["opacity"] for row in shadow_active),
            "median_shadow_softness": median_or_none(row["shadow"]["softness"] for row in shadow_active),
            "representative_shadow_color": robust_profile_color([row["shadow"]["color"] for row in shadow_active]),
            "source_counts": dict(Counter(row["source"] for row in rows)),
        }

    outline_enabled_count = sum(bool(row["source_effect"]["outline"]["enabled"]) for row in items)
    shadow_enabled_count = sum(bool(row["source_effect"]["shadow"]["enabled"]) for row in items)
    animated_caption_count = sum(bool(row["protected_animation_targets"]) for row in items)
    animation_target_count = sum(len(row["protected_animation_targets"]) for row in items)

    plan: Dict[str, Any] = {
        "ok": not failures,
        "schema": "video_cloner_caption_outline_shadow_full_rollout_plan",
        "schema_version": "2.0",
        "version": VERSION,
        "step": "Major Step 3B.3B",
        "mode": "full_v3_rollout_from_accepted_probe",
        "inputs": {
            "font_report": str(font_report_path),
            "font_report_sha256": hashlib.sha256(font_report_path.read_bytes()).hexdigest(),
            "step_3c_report": str(step_3c_report_path),
            "step_3c_report_sha256": hashlib.sha256(step_3c_report_path.read_bytes()).hexdigest(),
            "probe_idempotency_validation": str(probe_validation_path),
            "probe_idempotency_validation_sha256": hashlib.sha256(probe_validation_path.read_bytes()).hexdigest(),
        },
        "expected_v3_count": expected,
        "expected_rollout_target_count": expected_targets,
        "accepted_probe_cue_id": str(args.accepted_probe_cue_id),
        "outline_element": 2,
        "shadow_element": 3,
        "known_visual_debt": {
            "fill_color_fidelity": "deferred",
            "statement": "The current V3 fill color is preserved. This step does not correct the white-vs-dark-gray mismatch.",
        },
        "summary": {
            "v3_item_count": len(items),
            "profile_count": len(profile_calibration),
            "rollout_target_count": len(targets),
            "disabled_both_count": len(disabled),
            "outline_enabled_count": outline_enabled_count,
            "shadow_enabled_count": shadow_enabled_count,
            "animated_caption_protection_count": animated_caption_count,
            "protected_animation_target_count": animation_target_count,
            "accepted_probe_count": len(accepted_probe),
        },
        "profile_calibration": profile_calibration,
        "items": items,
        "warnings": warnings,
        "failures": failures,
    }
    plan["plan_hash"] = canonical_hash(plan)
    write_json(output_plan, plan)

    checks = {
        "font_report_ok": bool(font_report.get("ok")),
        "step_3c_gate_ok": not validate_step_3c_gate(step_3c_report),
        "probe_gate_ok": not validate_probe_gate(probe_validation),
        "v3_item_count": len(items) == expected,
        "unique_item_names": len(seen_names) == expected,
        "unique_cue_ids": len(seen_cues) == expected,
        "profile_count": len(profile_calibration) == 4,
        "rollout_target_count": len(targets) == expected_targets,
        "disabled_both_count": len(disabled) == expected - expected_targets,
        "outline_source_count": outline_enabled_count == expected_targets,
        "shadow_source_count": shadow_enabled_count == expected_targets,
        "accepted_probe_count": len(accepted_probe) == 1 and accepted_probe[0]["rollout_selected"],
        "animated_caption_count": animated_caption_count == 8,
        "protected_animation_target_count": animation_target_count == 16,
        "plan_ok": not failures,
    }
    validation = {
        "ok": all(checks.values()) and not failures,
        "step": "Major Step 3B.3B",
        "validator_version": VERSION,
        "plan": str(output_plan),
        "plan_hash": plan["plan_hash"],
        "checks": checks,
        "summary": plan["summary"],
        "warnings": warnings,
        "failures": failures + [f"check_failed:{key}" for key, value in checks.items() if not value],
    }
    write_json(output_validation, validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    return 0 if validation["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
