#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

VERSION = "prepare_caption_font_size_step_3B_2_v1_0_font_metric_profile_calibration"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def finite(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        number = float(value)
    except Exception:
        return default
    return number if math.isfinite(number) else default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def percentile(values: Sequence[float], fraction: float) -> float:
    rows = sorted(float(v) for v in values)
    if not rows:
        raise ValueError("Cannot calculate a percentile from an empty sequence")
    if len(rows) == 1:
        return rows[0]
    position = clamp(fraction, 0.0, 1.0) * (len(rows) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return rows[lower]
    blend = position - lower
    return rows[lower] * (1.0 - blend) + rows[upper] * blend


def robust_center(values: Sequence[float]) -> Tuple[float, List[float], float]:
    rows = [float(v) for v in values if math.isfinite(float(v))]
    if not rows:
        raise ValueError("No finite calibration samples")
    median = statistics.median(rows)
    deviations = [abs(value - median) for value in rows]
    mad = statistics.median(deviations) if deviations else 0.0
    if mad <= 1e-9:
        trimmed = rows
    else:
        limit = 3.5 * 1.4826 * mad
        trimmed = [value for value in rows if abs(value - median) <= limit]
        if not trimmed:
            trimmed = rows
    return statistics.median(trimmed), trimmed, mad


def extract_source_metrics(item: Dict[str, Any]) -> Dict[str, Any]:
    resolution = item.get("profile_resolution") or {}
    details = resolution.get("details") or {}
    source_height = None
    stroke_width = 0.0
    shadow_blur = 0.0
    bbox = None
    normalized_bbox = None
    source = resolution.get("source")

    event = details.get("event") if isinstance(details, dict) else None
    group = details.get("group") if isinstance(details, dict) else None
    if isinstance(event, dict):
        typography = event.get("typography") or {}
        placement = event.get("placement") or {}
        stroke = event.get("stroke") or {}
        shadow = event.get("shadow") or {}
        source_height = finite(typography.get("font_height_px"))
        bbox = placement.get("bbox")
        normalized_bbox = placement.get("normalized_bbox")
        if stroke.get("enabled"):
            stroke_width = finite(stroke.get("width_px_estimate"), 0.0) or 0.0
        if shadow.get("enabled"):
            shadow_blur = finite(shadow.get("blur_px_estimate"), 0.0) or 0.0
    elif isinstance(group, dict):
        source_height = finite(group.get("estimated_font_height_px"))
        bbox = group.get("bbox")
        normalized_bbox = group.get("normalized_bbox")
        if group.get("has_dark_stroke"):
            stroke_width = 3.0
        if group.get("has_shadow"):
            shadow_blur = 2.0

    if source_height is None and isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        y1, y2 = finite(bbox[1]), finite(bbox[3])
        if y1 is not None and y2 is not None:
            source_height = max(0.0, y2 - y1)

    return {
        "source": source,
        "font_height_px": source_height,
        "stroke_width_px": stroke_width,
        "shadow_blur_px": shadow_blur,
        "bbox": bbox,
        "normalized_bbox": normalized_bbox,
    }


def clean_probe_text(value: Any) -> str:
    text = " ".join(str(value or "").split())
    printable = "".join(ch for ch in text if ch.isprintable())
    return printable[:80] or "HgAy09"


def font_visible_ratio(font_file: Path, text: str, probe_em_px: int) -> Dict[str, Any]:
    try:
        from PIL import ImageFont  # type: ignore
    except Exception as exc:
        raise RuntimeError("Pillow is required. Run this script with venv_ocr.") from exc

    font = ImageFont.truetype(str(font_file), size=int(probe_em_px))

    def ratio_for(sample: str) -> float:
        bbox = font.getbbox(sample, stroke_width=0)
        if not bbox or len(bbox) < 4:
            return 0.0
        return max(0.0, float(bbox[3] - bbox[1]) / float(probe_em_px))

    actual = ratio_for(clean_probe_text(text))
    generic = ratio_for("HgAy09")
    if actual <= 0.05:
        actual = generic
    blended = clamp(actual * 0.65 + generic * 0.35, 0.35, 1.35)
    return {
        "actual_text_ratio": round(actual, 8),
        "generic_ratio": round(generic, 8),
        "blended_ratio": round(blended, 8),
    }


def keyframes_empty(value: Any) -> bool:
    return value in (None, {}, [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Resolve-safe Step 3B.2 size-calibration plan.")
    parser.add_argument("--step-3b1-report", required=True)
    parser.add_argument("--output-plan", required=True)
    parser.add_argument("--output-validation", required=True)
    parser.add_argument("--frame-width", type=int, default=1080)
    parser.add_argument("--frame-height", type=int, default=1920)
    parser.add_argument("--expected-v3-count", type=int, default=116)
    parser.add_argument("--probe-em-px", type=int, default=1000)
    parser.add_argument("--profile-shrinkage", type=float, default=0.85)
    parser.add_argument("--min-profile-multiplier", type=float, default=0.72)
    parser.add_argument("--max-profile-multiplier", type=float, default=1.20)
    parser.add_argument("--min-target-size", type=float, default=0.025)
    parser.add_argument("--max-target-size", type=float, default=0.32)
    parser.add_argument("--min-source-height-px", type=float, default=24.0)
    parser.add_argument("--max-source-height-px", type=float, default=240.0)
    parser.add_argument("--encoding", default="utf-8")
    args = parser.parse_args()

    started = time.time()
    report_path = Path(args.step_3b1_report)
    output_plan = Path(args.output_plan)
    output_validation = Path(args.output_validation)
    report = load_json(report_path)
    failures: List[str] = []
    warnings: List[str] = []

    if not report.get("ok"):
        failures.append("step_3B_1_report_ok_false")
    if int(report.get("v3_candidate_count") or 0) != args.expected_v3_count:
        failures.append("step_3B_1_v3_count_mismatch")
    if int(report.get("readback_success_count") or 0) != args.expected_v3_count:
        failures.append("step_3B_1_font_readback_incomplete")
    if int(report.get("failed_count") or 0) != 0:
        failures.append("step_3B_1_has_failures")

    source_items = [row for row in (report.get("items") or []) if isinstance(row, dict)]
    if len(source_items) != args.expected_v3_count:
        failures.append("step_3B_1_item_count_mismatch")

    metric_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
    candidates: List[Dict[str, Any]] = []
    profile_ratios: Dict[str, List[float]] = {}
    profile_counts: Dict[str, int] = {}
    font_files_seen: Dict[str, Dict[str, Any]] = {}
    animated_size_count = 0

    for row in source_items:
        name = str(row.get("name") or "")
        profile_id = str((row.get("profile_resolution") or {}).get("style_profile_id") or "")
        mapping = row.get("mapping") or {}
        font_file = Path(str(mapping.get("font_file") or ""))
        family = str(mapping.get("family") or "")
        face = str(mapping.get("face") or "Regular")
        text = str(row.get("rendered_text") or "")
        size_info = ((row.get("preserved_inputs_after") or {}).get("Size") or {})
        current_size = finite(size_info.get("value"))
        size_keyframes = size_info.get("keyframes")
        if not keyframes_empty(size_keyframes):
            animated_size_count += 1

        source = extract_source_metrics(row)
        source_height = finite(source.get("font_height_px"))
        profile_counts[profile_id] = profile_counts.get(profile_id, 0) + 1
        font_files_seen.setdefault(str(font_file), {
            "font_file": str(font_file), "family": family, "face": face,
            "exists": font_file.is_file(), "loaded": False, "error": None,
        })

        metric_error = None
        metrics = None
        cache_key = (str(font_file), clean_probe_text(text))
        if cache_key in metric_cache:
            metrics = metric_cache[cache_key]
        else:
            try:
                if not font_file.is_file():
                    raise FileNotFoundError(font_file)
                metrics = font_visible_ratio(font_file, text, args.probe_em_px)
                metric_cache[cache_key] = metrics
                font_files_seen[str(font_file)]["loaded"] = True
            except Exception as exc:
                metric_error = f"{type(exc).__name__}: {exc}"
                font_files_seen[str(font_file)]["error"] = metric_error

        reliable = True
        reasons: List[str] = []
        if current_size is None or current_size <= 0:
            reliable = False
            reasons.append("invalid_current_size")
        if source_height is None or not (args.min_source_height_px <= source_height <= args.max_source_height_px):
            reliable = False
            reasons.append("source_height_out_of_range")
        if metrics is None:
            reliable = False
            reasons.append("font_metric_unavailable")
        if not keyframes_empty(size_keyframes):
            reliable = False
            reasons.append("size_keyframes_present")

        raw_target = None
        raw_multiplier = None
        core_height = None
        if reliable and metrics is not None and current_size is not None and source_height is not None:
            core_height = max(
                1.0,
                source_height
                - 2.0 * float(source.get("stroke_width_px") or 0.0)
                - 0.5 * float(source.get("shadow_blur_px") or 0.0),
            )
            visible_ratio = float(metrics["blended_ratio"])
            raw_target = core_height / (float(args.frame_width) * visible_ratio)
            raw_multiplier = raw_target / current_size
            if not (0.40 <= raw_multiplier <= 2.50):
                reliable = False
                reasons.append("raw_multiplier_out_of_range")
            else:
                profile_ratios.setdefault(profile_id, []).append(raw_multiplier)

        candidates.append({
            "name": name,
            "cue_id": row.get("cue_id"),
            "cue_index": row.get("cue_index"),
            "start": row.get("start"),
            "end": row.get("end"),
            "rendered_text": text,
            "style_profile_id": profile_id,
            "expected_family": family,
            "expected_face": face,
            "font_file": str(font_file),
            "baseline_size": current_size,
            "baseline_size_keyframes": size_keyframes,
            "source_metrics": source,
            "font_metrics": metrics,
            "font_metric_error": metric_error,
            "core_visible_height_px": round(core_height, 6) if core_height is not None else None,
            "raw_target_size": round(raw_target, 12) if raw_target is not None else None,
            "raw_multiplier": round(raw_multiplier, 8) if raw_multiplier is not None else None,
            "calibration_sample_accepted": reliable,
            "calibration_rejection_reasons": reasons,
        })

    profile_calibration: Dict[str, Dict[str, Any]] = {}
    for profile_id, count in sorted(profile_counts.items()):
        values = profile_ratios.get(profile_id, [])
        if not values:
            failures.append(f"no_reliable_size_samples:{profile_id}")
            continue
        center, trimmed, mad = robust_center(values)
        shrunken = 1.0 + (center - 1.0) * clamp(args.profile_shrinkage, 0.0, 1.0)
        multiplier = clamp(shrunken, args.min_profile_multiplier, args.max_profile_multiplier)
        profile_calibration[profile_id] = {
            "profile_id": profile_id,
            "item_count": count,
            "reliable_sample_count": len(values),
            "trimmed_sample_count": len(trimmed),
            "raw_multiplier_median": round(center, 8),
            "raw_multiplier_p10": round(percentile(values, 0.10), 8),
            "raw_multiplier_p90": round(percentile(values, 0.90), 8),
            "raw_multiplier_mad": round(mad, 8),
            "profile_shrinkage": args.profile_shrinkage,
            "applied_multiplier": round(multiplier, 8),
            "clamped": abs(multiplier - shrunken) > 1e-9,
        }

    plan_items: List[Dict[str, Any]] = []
    for row in candidates:
        profile_id = row["style_profile_id"]
        calibration = profile_calibration.get(profile_id)
        baseline = finite(row.get("baseline_size"))
        if calibration is None or baseline is None:
            target = None
        else:
            target = clamp(
                baseline * float(calibration["applied_multiplier"]),
                args.min_target_size,
                args.max_target_size,
            )
        item = dict(row)
        item["profile_multiplier"] = calibration.get("applied_multiplier") if calibration else None
        item["target_size"] = round(target, 12) if target is not None else None
        item["target_change_ratio"] = round(target / baseline, 8) if target is not None and baseline else None
        plan_items.append(item)

    if len(plan_items) != args.expected_v3_count:
        failures.append("plan_item_count_mismatch")
    if any(row.get("target_size") is None for row in plan_items):
        failures.append("plan_contains_missing_target_size")
    if animated_size_count:
        failures.append(f"animated_size_inputs_not_supported_in_this_isolated_pass:{animated_size_count}")

    review_samples = []
    fps = finite(report.get("timeline_fps"), 24.0) or 24.0
    for profile_id in sorted(profile_calibration):
        rows = [row for row in plan_items if row.get("style_profile_id") == profile_id]
        median_target = statistics.median(float(row["target_size"]) for row in rows if row.get("target_size") is not None)
        rows.sort(key=lambda row: abs(float(row.get("target_size") or 0.0) - median_target))
        for row in rows[:2]:
            review_samples.append({
                "style_profile_id": profile_id,
                "name": row.get("name"),
                "cue_id": row.get("cue_id"),
                "rendered_text": row.get("rendered_text"),
                "timeline_frame": row.get("start"),
                "timeline_seconds": round(float(row.get("start") or 0) / fps, 6),
                "baseline_size": row.get("baseline_size"),
                "target_size": row.get("target_size"),
                "family": row.get("expected_family"),
                "face": row.get("expected_face"),
            })

    loaded_fonts = sum(1 for row in font_files_seen.values() if row.get("loaded"))
    expected_fonts = len(font_files_seen)
    if loaded_fonts != expected_fonts:
        failures.append("not_all_approved_font_files_loaded")

    plan = {
        "ok": len(failures) == 0,
        "step": "Major Step 3B.2",
        "version": VERSION,
        "created_at_unix": round(time.time(), 6),
        "source_step_3B_1_report": str(report_path),
        "video_id": "DZsqH7auhjt",
        "timeline_name": report.get("timeline_name"),
        "timeline_fps": fps,
        "frame_width": args.frame_width,
        "frame_height": args.frame_height,
        "reference_dimension": "frame_width",
        "algorithm": {
            "description": "Font-aware profile calibration from detected visible caption height and approved-font glyph metrics.",
            "raw_target_formula": "core_visible_height_px / (frame_width * blended_font_visible_ratio)",
            "application_policy": "Apply one robust multiplier per approved style profile, preserving all existing per-cue relative size differences.",
            "stroke_policy": "Subtract estimated outline contribution before body-size fitting; Step 3C will add outline/shadow fidelity.",
            "probe_em_px": args.probe_em_px,
            "profile_shrinkage": args.profile_shrinkage,
            "profile_multiplier_bounds": [args.min_profile_multiplier, args.max_profile_multiplier],
            "target_size_bounds": [args.min_target_size, args.max_target_size],
        },
        "expected_v3_count": args.expected_v3_count,
        "plan_item_count": len(plan_items),
        "profile_count": len(profile_calibration),
        "animated_size_input_count": animated_size_count,
        "font_files": list(font_files_seen.values()),
        "profile_calibration": profile_calibration,
        "profile_item_counts": profile_counts,
        "visual_review_samples": review_samples,
        "items": plan_items,
        "warnings": warnings,
        "failures": failures,
        "runtime_seconds": round(time.time() - started, 3),
    }
    write_json(output_plan, plan)

    validation = {
        "ok": plan["ok"],
        "step": "Major Step 3B.2 plan preparation",
        "validator_version": "validate_caption_font_size_plan_step_3B_2_v1_0",
        "plan": str(output_plan),
        "checks": {
            "source_step_3B_1_ok": bool(report.get("ok")),
            "expected_v3_count": len(source_items) == args.expected_v3_count,
            "plan_item_count": len(plan_items) == args.expected_v3_count,
            "profile_count": len(profile_calibration) == len(profile_counts) and len(profile_counts) > 0,
            "all_font_files_loaded": loaded_fonts == expected_fonts,
            "all_targets_present": all(row.get("target_size") is not None for row in plan_items),
            "no_size_keyframes": animated_size_count == 0,
        },
        "summary": {
            "source_item_count": len(source_items),
            "plan_item_count": len(plan_items),
            "profile_count": len(profile_calibration),
            "font_file_count": expected_fonts,
            "font_files_loaded": loaded_fonts,
            "animated_size_input_count": animated_size_count,
            "profile_calibration": profile_calibration,
            "visual_review_samples": review_samples,
        },
        "warnings": warnings,
        "failures": failures,
    }
    write_json(output_validation, validation)
    print(json.dumps({
        "success": validation["ok"],
        "plan": str(output_plan),
        "validation": str(output_validation),
        "items": len(plan_items),
        "profiles": len(profile_calibration),
        "profile_multipliers": {k: v["applied_multiplier"] for k, v in profile_calibration.items()},
        "visual_review_samples": review_samples,
        "failures": failures,
    }, ensure_ascii=False, indent=2))
    return 0 if validation["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
