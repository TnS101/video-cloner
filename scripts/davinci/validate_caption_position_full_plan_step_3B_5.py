#!/usr/bin/env python3
"""Validate Major Step 3B.5B full-position rollout plan."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

VERSION = "validate_caption_position_full_plan_step_3B_5B_v1_0"
EXPECTED_V3_COUNT = 116


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def canonical_hash(value: Dict[str, Any]) -> str:
    clean = dict(value)
    clean.pop("plan_hash", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    plan_path = Path(args.plan).resolve()
    output_path = Path(args.output).resolve()
    failures: List[str] = []
    try:
        plan = load_json(plan_path)
    except Exception as exc:
        payload = {"ok": False, "step": "Major Step 3B.5B", "validator_version": VERSION, "failures": [f"plan_load_failed:{type(exc).__name__}:{exc}"]}
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2))
        return 1

    items = [row for row in (plan.get("items") or []) if isinstance(row, dict)]
    accepted = [row for row in items if row.get("accepted_probe")]
    animated = [row for row in items if row.get("position_write_mode") == "translated_center_animation"]
    static = [row for row in items if row.get("position_write_mode") == "static_center"]
    summary = plan.get("summary") or {}
    checks = {
        "plan_ok": bool(plan.get("ok")),
        "schema": plan.get("schema") == "video_cloner_caption_position_full_rollout_plan",
        "step": plan.get("step") == "Major Step 3B.5B",
        "plan_hash": plan.get("plan_hash") == canonical_hash(plan),
        "v3_item_count": len(items) == EXPECTED_V3_COUNT == int(summary.get("v3_item_count") or 0),
        "rollout_target_count": sum(1 for row in items if row.get("rollout_target")) == EXPECTED_V3_COUNT == int(summary.get("rollout_target_count") or 0),
        "unique_names": len({row.get("name") for row in items}) == EXPECTED_V3_COUNT,
        "unique_cues": len({row.get("cue_id") for row in items}) == EXPECTED_V3_COUNT,
        "accepted_probe_count": len(accepted) == 1 == int(summary.get("accepted_probe_count") or 0),
        "accepted_probe": bool(accepted and accepted[0].get("cue_id") == "sub_034" and accepted[0].get("target_center") == [0.3833, 0.6724]),
        "direct_event_count": int(summary.get("direct_event_position_count") or 0) == 66,
        "near_group_count": int(summary.get("near_group_position_count") or 0) == 33,
        "interpolated_count": int(summary.get("interpolated_position_count") or 0) == 16,
        "nearest_event_count": int(summary.get("nearest_event_position_count") or 0) == 1,
        "profile_median_count": int(summary.get("profile_median_position_count") or 0) == 0,
        "static_caption_count": len(static) == 112 == int(summary.get("static_center_caption_count") or 0),
        "animated_caption_count": len(animated) == 4 == int(summary.get("translated_center_animation_caption_count") or 0),
        "translated_keyframe_count": int(summary.get("translated_center_keyframe_count") or 0) == 8,
        "animation_target_count_before": sum(len(row.get("protected_animation_targets_before") or []) for row in items) == 16 == int(summary.get("animation_target_count_before") or 0),
        "animation_target_count_after": sum(len(row.get("expected_animation_targets_after") or []) for row in items) == 16 == int(summary.get("animation_target_count_after") or 0),
        "animated_targets_are_center": all(sum(1 for t in row.get("expected_animation_targets_after") or [] if t.get("input") == "Center") == 2 for row in animated),
        "all_target_centers_valid": all(isinstance(row.get("target_center"), list) and len(row.get("target_center")) == 2 for row in items),
        "no_plan_failures": not plan.get("failures"),
    }
    failures.extend(key for key, passed in checks.items() if not passed)
    payload = {
        "ok": not failures,
        "step": "Major Step 3B.5B",
        "validator_version": VERSION,
        "plan": str(plan_path),
        "summary": summary,
        "checks": checks,
        "warnings": plan.get("warnings") or [],
        "failures": failures,
        "output": str(output_path),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
