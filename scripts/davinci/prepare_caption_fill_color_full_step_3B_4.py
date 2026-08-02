#!/usr/bin/env python3
"""Build Major Step 3B.4B full source-fill rollout plan."""
from __future__ import annotations
import argparse, hashlib, json, math, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

VERSION = "prepare_caption_fill_color_full_step_3B_4B_v1_0"
EXPECTED_V3_COUNT = 116
EXPECTED_DIRECT_EVENT_FILL_COUNT = 66
EXPECTED_GROUP_ESTIMATED_FILL_COUNT = 50


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
    clean = dict(value); clean.pop("plan_hash", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def finite(value: Any, default: Optional[float] = None) -> Optional[float]:
    try: number = float(value)
    except (TypeError, ValueError): return default
    return number if math.isfinite(number) else default


def normalize_hex(value: Any) -> str:
    text = str(value or "").strip().lower()
    if len(text) == 4 and text.startswith("#"):
        text = "#" + "".join(ch * 2 for ch in text[1:])
    if len(text) == 7 and text.startswith("#"):
        try:
            int(text[1:], 16)
            return text
        except ValueError:
            pass
    raise ValueError(f"Invalid six-digit color: {value!r}")


def rgb(hex_color: str) -> Tuple[float, float, float]:
    color = normalize_hex(hex_color)
    return tuple(round(int(color[i:i+2], 16) / 255.0, 8) for i in (1, 3, 5))  # type: ignore[return-value]


def validate_gate(payload: Dict[str, Any], step: str, mode: str) -> List[str]:
    failures: List[str] = []
    if not payload.get("ok"): failures.append(f"{step}_not_ok")
    if payload.get("mode") != mode and payload.get("run_mode") != mode: failures.append(f"{step}_wrong_mode")
    if payload.get("failures"): failures.append(f"{step}_has_failures")
    return failures


def source_fill(font_item: Dict[str, Any]) -> Dict[str, Any]:
    resolution = font_item.get("profile_resolution") or {}
    details = resolution.get("details") or {}
    event = details.get("event") if isinstance(details, dict) else None
    group = details.get("group") if isinstance(details, dict) else None
    if isinstance(event, dict):
        colors = event.get("colors") or {}
        value = colors.get("fill")
        if value:
            color = normalize_hex(value)
            r, g, b = rgb(color)
            confidence = event.get("confidence") or {}
            return {
                "hex": color, "red": r, "green": g, "blue": b, "alpha": 1.0,
                "source": "caption_style_event.colors.fill",
                "source_detail_id": event.get("event_id"),
                "confidence_score": confidence.get("score"),
                "confidence_label": confidence.get("label"),
                "observations_count": confidence.get("observations_count"),
            }
    if isinstance(group, dict) and group.get("estimated_text_color"):
        color = normalize_hex(group.get("estimated_text_color"))
        r, g, b = rgb(color)
        return {
            "hex": color, "red": r, "green": g, "blue": b, "alpha": 1.0,
            "source": "classified_caption_group.estimated_text_color",
            "source_detail_id": group.get("frame_index"),
            "confidence_score": resolution.get("confidence", group.get("confidence")),
            "confidence_label": "classified_group_estimate",
            "observations_count": None,
        }
    raise ValueError(f"No source-supported fill for {font_item.get('name')}")


def build(args: argparse.Namespace):
    font_path = Path(args.font_report).resolve()
    step3c_path = Path(args.step_3c_report).resolve()
    effect_report_path = Path(args.step_3b3c_idempotency_report).resolve()
    effect_validation_path = Path(args.step_3b3c_idempotency_validation).resolve()
    font = load_json(font_path)
    step3c = load_json(step3c_path)
    effect_report = load_json(effect_report_path)
    effect_validation = load_json(effect_validation_path)
    failures: List[str] = []
    warnings = [
        "66 cues use direct caption-style-event fills; 50 cues use classified-group estimated text colors. Review representative captions from every retained style profile after the first pass.",
        "The darkest-text-component substitution is disabled. No caption is forced to white or black globally."
    ]
    if not font.get("ok") or int(font.get("v3_candidate_count") or 0) != args.expected_v3_count:
        failures.append("font_report_gate_failed")
    failures.extend(validate_gate(step3c, "step_3C", "idempotent_second_run"))
    failures.extend(validate_gate(effect_report, "step_3B_3C_report", "idempotent_second_run"))
    failures.extend(validate_gate(effect_validation, "step_3B_3C_validation", "idempotent_second_run"))
    effect_summary = effect_report.get("summary") or {}
    if int(effect_summary.get("glow_verified_count") or 0) != 99 or int(effect_summary.get("retained_outline_verified_count") or 0) != 14 or int(effect_summary.get("no_effect_verified_count") or 0) != 3:
        failures.append("step_3B_3C_effect_integrity")
    if int(effect_summary.get("protected_fill_verified_count") or 0) != args.expected_v3_count:
        failures.append("step_3B_3C_fill_integrity")
    if int(effect_summary.get("protected_animation_verified_count") or 0) != 16:
        failures.append("step_3B_3C_animation_integrity")

    step3c_items = {str(row.get("cue_id")): row for row in (step3c.get("items") or []) if isinstance(row, dict) and row.get("cue_id")}
    effect_items = {str(row.get("cue_id")): row for row in (effect_report.get("items") or []) if isinstance(row, dict) and row.get("cue_id")}
    items: List[Dict[str, Any]] = []
    seen_names, seen_cues = set(), set()
    source_counts: Dict[str, int] = {}
    profile_counts: Dict[str, int] = {}
    for row in font.get("items") or []:
        if not isinstance(row, dict):
            failures.append("non_object_font_item"); continue
        name = str(row.get("name") or ""); cue_id = str(row.get("cue_id") or "")
        if not name or not cue_id or name in seen_names or cue_id in seen_cues:
            failures.append(f"invalid_or_duplicate_item:{name}:{cue_id}"); continue
        seen_names.add(name); seen_cues.add(cue_id)
        try:
            fill = source_fill(row)
        except Exception as exc:
            failures.append(f"fill_source_failed:{name}:{type(exc).__name__}:{exc}"); continue
        source_counts[fill["source"]] = source_counts.get(fill["source"], 0) + 1
        resolution = row.get("profile_resolution") or {}
        profile_id = str(resolution.get("style_profile_id") or "")
        profile_counts[profile_id] = profile_counts.get(profile_id, 0) + 1
        effect_row = effect_items.get(cue_id) or {}
        effect_mode = str(effect_row.get("classification_mode") or "")
        if effect_mode not in {"shadow_glow_only", "outline_and_shadow", "none"}:
            failures.append(f"missing_or_invalid_effect_mode:{name}:{effect_mode}")
        targets = []
        for target in (step3c_items.get(cue_id) or {}).get("targets") or []:
            if isinstance(target, dict):
                targets.append({"input": target.get("input"), "local_frame": int(target.get("local_frame") or 0), "expected": target.get("expected")})
        items.append({
            "name": name, "cue_id": cue_id,
            "cue_index": int(row.get("cue_index") or row.get("cue_number") or 0),
            "start": int(row.get("start") or 0), "end": int(row.get("end") or 0),
            "text": str(row.get("rendered_text") or ""),
            "expected_font_family": str(row.get("font_after") or row.get("requested_family") or ""),
            "expected_font_face": str(row.get("style_after") or row.get("requested_face") or ""),
            "style_profile_id": profile_id,
            "target_fill": fill,
            "protected_effect_mode": effect_mode,
            "protected_animation_targets": targets,
        })
    items.sort(key=lambda row: (row["cue_index"], row["name"]))
    direct_count = source_counts.get("caption_style_event.colors.fill", 0)
    group_count = source_counts.get("classified_caption_group.estimated_text_color", 0)
    animation_target_count = sum(len(row["protected_animation_targets"]) for row in items)
    if len(items) != args.expected_v3_count: failures.append("v3_item_count_mismatch")
    if direct_count != args.expected_direct_event_fill_count: failures.append(f"direct_event_fill_count_mismatch:{direct_count}")
    if group_count != args.expected_group_estimated_fill_count: failures.append(f"group_estimated_fill_count_mismatch:{group_count}")
    if animation_target_count != 16: failures.append("animation_target_count_mismatch")
    if len(effect_items) != args.expected_v3_count: failures.append("effect_report_item_count_mismatch")

    plan: Dict[str, Any] = {
        "ok": not failures,
        "schema": "video_cloner_caption_fill_color_full_plan",
        "schema_version": "1.0",
        "step": "Major Step 3B.4B",
        "planner_version": VERSION,
        "created_at_unix": round(time.time(), 6),
        "expected_v3_count": args.expected_v3_count,
        "policy": {
            "primary": "caption_style_event.colors.fill",
            "fallback": "classified_caption_group.estimated_text_color",
            "forbidden": "darkest_text_component_on_low_confidence",
            "global_force_color": None,
            "alpha": 1.0,
        },
        "inputs": {
            "font_report": str(font_path),
            "step_3c_idempotency_report": str(step3c_path),
            "step_3B_3C_idempotency_report": str(effect_report_path),
            "step_3B_3C_idempotency_validation": str(effect_validation_path),
        },
        "summary": {
            "v3_item_count": len(items),
            "direct_event_fill_count": direct_count,
            "group_estimated_fill_count": group_count,
            "protected_effect_count": len(items),
            "protected_animation_target_count": animation_target_count,
            "profile_item_counts": profile_counts,
            "unique_target_fill_count": len({row["target_fill"]["hex"] for row in items}),
        },
        "items": items, "warnings": warnings, "failures": failures,
    }
    plan["plan_hash"] = canonical_hash(plan)
    checks = {
        "font_report_gate": "font_report_gate_failed" not in failures,
        "step_3C_gate": not any(row.startswith("step_3C") for row in failures),
        "step_3B_3C_gate": not any(row.startswith("step_3B_3C") for row in failures),
        "v3_item_count": len(items) == args.expected_v3_count,
        "unique_names": len(seen_names) == args.expected_v3_count,
        "unique_cues": len(seen_cues) == args.expected_v3_count,
        "direct_event_fill_count": direct_count == args.expected_direct_event_fill_count,
        "group_estimated_fill_count": group_count == args.expected_group_estimated_fill_count,
        "protected_effect_count": len(effect_items) == args.expected_v3_count,
        "protected_animation_target_count": animation_target_count == 16,
        "plan_ok": not failures,
    }
    validation = {
        "ok": all(checks.values()) and not failures, "step": "Major Step 3B.4B",
        "validator_version": VERSION, "plan": str(Path(args.output_plan).resolve()),
        "plan_hash": plan["plan_hash"], "checks": checks, "summary": plan["summary"],
        "warnings": warnings,
        "failures": failures + [f"check_failed:{key}" for key, ok in checks.items() if not ok],
    }
    return plan, validation


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--font-report", required=True)
    p.add_argument("--step-3c-report", required=True)
    p.add_argument("--step-3b3c-idempotency-report", required=True)
    p.add_argument("--step-3b3c-idempotency-validation", required=True)
    p.add_argument("--output-plan", required=True)
    p.add_argument("--output-validation", required=True)
    p.add_argument("--expected-v3-count", type=int, default=EXPECTED_V3_COUNT)
    p.add_argument("--expected-direct-event-fill-count", type=int, default=EXPECTED_DIRECT_EVENT_FILL_COUNT)
    p.add_argument("--expected-group-estimated-fill-count", type=int, default=EXPECTED_GROUP_ESTIMATED_FILL_COUNT)
    args = p.parse_args()
    try:
        plan, validation = build(args)
    except Exception as exc:
        validation = {"ok": False, "step": "Major Step 3B.4B", "validator_version": VERSION, "failures": [f"{type(exc).__name__}: {exc}"]}
        write_json(Path(args.output_validation), validation)
        print(json.dumps(validation, indent=2)); return 1
    write_json(Path(args.output_plan), plan); write_json(Path(args.output_validation), validation)
    print(json.dumps(validation, indent=2)); return 0 if validation.get("ok") else 1


if __name__ == "__main__": raise SystemExit(main())
