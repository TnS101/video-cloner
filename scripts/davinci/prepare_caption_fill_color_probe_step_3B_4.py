#!/usr/bin/env python3
"""Build Major Step 3B.4A detected-fill correction probe plan."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

VERSION = "prepare_caption_fill_color_probe_step_3B_4_v1_0"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp.replace(path)


def canonical_hash(payload: Dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("plan_hash", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def parse_hex_color(value: Any) -> Tuple[float, float, float]:
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"Invalid six-digit fill color: {value!r}")
    try:
        return tuple(round(int(text[i:i + 2], 16) / 255.0, 8) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as exc:
        raise ValueError(f"Invalid fill color: {value!r}") from exc


def find_font_item(report: Dict[str, Any], cue_id: str) -> Dict[str, Any]:
    rows = [row for row in (report.get("items") or []) if isinstance(row, dict) and row.get("cue_id") == cue_id]
    if len(rows) != 1:
        raise ValueError(f"Font report must contain exactly one {cue_id} item; found {len(rows)}")
    return rows[0]


def find_animation_item(report: Dict[str, Any], cue_id: str) -> Dict[str, Any]:
    rows = [row for row in (report.get("items") or []) if isinstance(row, dict) and row.get("cue_id") == cue_id]
    if len(rows) != 1:
        raise ValueError(f"Step 3C report must contain exactly one animated {cue_id} item; found {len(rows)}")
    return rows[0]


def build_plan(args: argparse.Namespace) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    font_path = Path(args.font_report).resolve()
    step3c_path = Path(args.step_3c_report).resolve()
    baseline_report_path = Path(args.step_3b3b_idempotency_report).resolve()
    baseline_validation_path = Path(args.step_3b3b_idempotency_validation).resolve()

    font = load_json(font_path)
    step3c = load_json(step3c_path)
    baseline_report = load_json(baseline_report_path)
    baseline_validation = load_json(baseline_validation_path)

    failures: List[str] = []
    warnings: List[str] = []

    if not font.get("ok"):
        failures.append("font_report_not_ok")
    if int(font.get("v3_candidate_count") or 0) != args.expected_v3_count:
        failures.append("font_report_v3_count")
    if not step3c.get("ok") or step3c.get("run_mode") != "idempotent_second_run":
        failures.append("step_3c_idempotency_report_not_ok")
    if int((step3c.get("summary") or {}).get("readback_keyframe_count") or 0) != 16:
        failures.append("step_3c_keyframe_count")
    if not baseline_report.get("ok") or baseline_report.get("run_mode") != "idempotent_second_run":
        failures.append("step_3B_3B_idempotency_report_not_ok")
    if int((baseline_report.get("summary") or {}).get("protected_caption_verified_count") or 0) != args.expected_v3_count:
        failures.append("step_3B_3B_caption_integrity")
    if int((baseline_report.get("summary") or {}).get("outline_verified_count") or 0) != 113:
        failures.append("step_3B_3B_outline_integrity")
    if int((baseline_report.get("summary") or {}).get("shadow_verified_count") or 0) != 113:
        failures.append("step_3B_3B_shadow_integrity")
    if not baseline_validation.get("ok") or baseline_validation.get("mode") != "idempotent_second_run":
        failures.append("step_3B_3B_idempotency_validation_not_ok")

    font_item = find_font_item(font, args.probe_cue_id)
    animation_item = find_animation_item(step3c, args.probe_cue_id)
    profile = font_item.get("profile_resolution") or {}
    details = profile.get("details") or {}
    event = details.get("event") or {}
    colors = event.get("colors") or {}
    confidence = event.get("confidence") or {}
    detected_fill = colors.get("fill")
    if not detected_fill:
        failures.append("probe_detected_fill_missing")
        detected_fill = "#000000"
    try:
        red, green, blue = parse_hex_color(detected_fill)
    except ValueError:
        failures.append("probe_detected_fill_invalid")
        red, green, blue = (0.0, 0.0, 0.0)

    targets = []
    for row in animation_item.get("targets") or []:
        if not isinstance(row, dict):
            continue
        targets.append({
            "input": row.get("input"),
            "local_frame": int(row.get("local_frame") or 0),
            "expected": row.get("expected"),
        })
    if len(targets) != 2:
        failures.append("probe_animation_target_count")

    item = {
        "probe_selected": True,
        "cue_id": args.probe_cue_id,
        "name": font_item.get("name"),
        "start": int(font_item.get("start") or 0),
        "end": int(font_item.get("end") or 0),
        "text": font_item.get("rendered_text"),
        "style_profile_id": profile.get("style_profile_id"),
        "expected_font_family": (font_item.get("mapping") or {}).get("family"),
        "expected_font_face": (font_item.get("mapping") or {}).get("face"),
        "source_fill": {
            "hex": detected_fill,
            "red": red,
            "green": green,
            "blue": blue,
            "alpha": 1.0,
            "source": "caption_style_event.colors.fill",
            "event_id": event.get("event_id"),
            "event_confidence_score": confidence.get("score"),
            "event_confidence_label": confidence.get("label"),
            "observations_count": confidence.get("observations_count"),
        },
        "known_bad_policy": {
            "policy": "darkest_text_component_on_low_confidence",
            "problem": "The old renderer replaced a bright detected fill with the dark stroke color when confidence was below 0.70.",
            "replacement_policy": "use_detected_fill_without_darkest_component_substitution",
        },
        "protected_animation_targets": targets,
    }

    plan: Dict[str, Any] = {
        "ok": not failures,
        "step": "Major Step 3B.4A",
        "planner_version": VERSION,
        "created_at_unix": round(time.time(), 6),
        "expected_v3_count": args.expected_v3_count,
        "probe_cue_id": args.probe_cue_id,
        "inputs": {
            "font_report": str(font_path),
            "step_3c_idempotency_report": str(step3c_path),
            "step_3B_3B_idempotency_report": str(baseline_report_path),
            "step_3B_3B_idempotency_validation": str(baseline_validation_path),
        },
        "items": [item],
        "summary": {
            "probe_item_count": 1,
            "detected_fill_count": 1 if detected_fill else 0,
            "protected_animation_target_count": len(targets),
            "target_fill_hex": detected_fill,
        },
        "warnings": warnings,
        "failures": failures,
    }
    plan["plan_hash"] = canonical_hash(plan)

    validation = {
        "ok": plan["ok"],
        "step": "Major Step 3B.4A",
        "validator_version": VERSION,
        "plan": str(Path(args.output_plan).resolve()),
        "checks": {
            "font_report_ok": "font_report_not_ok" not in failures,
            "expected_v3_count": "font_report_v3_count" not in failures,
            "step_3c_idempotency": "step_3c_idempotency_report_not_ok" not in failures,
            "step_3c_targets": "step_3c_keyframe_count" not in failures and "probe_animation_target_count" not in failures,
            "step_3B_3B_idempotency_report": "step_3B_3B_idempotency_report_not_ok" not in failures,
            "step_3B_3B_idempotency_validation": "step_3B_3B_idempotency_validation_not_ok" not in failures,
            "outline_shadow_integrity": not any(x in failures for x in ("step_3B_3B_caption_integrity", "step_3B_3B_outline_integrity", "step_3B_3B_shadow_integrity")),
            "probe_fill_available": not any(x in failures for x in ("probe_detected_fill_missing", "probe_detected_fill_invalid")),
        },
        "summary": plan["summary"],
        "warnings": warnings,
        "failures": failures,
    }
    return plan, validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--font-report", required=True)
    parser.add_argument("--step-3c-report", required=True)
    parser.add_argument("--step-3b3b-idempotency-report", required=True)
    parser.add_argument("--step-3b3b-idempotency-validation", required=True)
    parser.add_argument("--output-plan", required=True)
    parser.add_argument("--output-validation", required=True)
    parser.add_argument("--expected-v3-count", type=int, default=116)
    parser.add_argument("--probe-cue-id", default="sub_019")
    args = parser.parse_args()

    try:
        plan, validation = build_plan(args)
    except Exception as exc:
        validation = {
            "ok": False,
            "step": "Major Step 3B.4A",
            "validator_version": VERSION,
            "failures": [f"{type(exc).__name__}: {exc}"],
        }
        write_json(Path(args.output_validation), validation)
        print(json.dumps(validation, indent=2))
        return 1

    write_json(Path(args.output_plan), plan)
    write_json(Path(args.output_validation), validation)
    print(json.dumps(validation, indent=2))
    return 0 if validation.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
