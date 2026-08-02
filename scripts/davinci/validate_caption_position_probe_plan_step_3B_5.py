#!/usr/bin/env python3
"""Validate Major Step 3B.5A position-probe plan."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

VERSION = "validate_caption_position_probe_plan_step_3B_5A_v1_0"
EXPECTED_V3_COUNT = 116
EXPECTED_PROBE_CUE = "sub_034"


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
        payload = {"ok": False, "step": "Major Step 3B.5A", "validator_version": VERSION, "failures": [f"plan_load_failed:{type(exc).__name__}:{exc}"]}
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2))
        return 1

    items = [row for row in (plan.get("items") or []) if isinstance(row, dict)]
    probes = [row for row in items if row.get("selected_probe")]
    summary = plan.get("summary") or {}
    checks = {
        "plan_ok": bool(plan.get("ok")),
        "schema": plan.get("schema") == "video_cloner_caption_position_probe_plan",
        "step": plan.get("step") == "Major Step 3B.5A",
        "plan_hash": plan.get("plan_hash") == canonical_hash(plan),
        "v3_item_count": len(items) == EXPECTED_V3_COUNT == int(summary.get("v3_item_count") or 0),
        "unique_names": len({row.get("name") for row in items}) == EXPECTED_V3_COUNT,
        "unique_cues": len({row.get("cue_id") for row in items}) == EXPECTED_V3_COUNT,
        "probe_count": len(probes) == 1 == int(summary.get("probe_item_count") or 0),
        "probe_cue": bool(probes and probes[0].get("cue_id") == EXPECTED_PROBE_CUE),
        "probe_target": bool(probes and probes[0].get("target_center") == [0.3833, 0.6724]),
        "probe_source": bool(probes and (probes[0].get("source_position") or {}).get("source") == "classified_caption_group.center_near_cue_time"),
        "probe_static": bool(probes and not probes[0].get("protected_animation_targets")),
        "direct_event_count": int(summary.get("direct_event_position_count") or 0) == 66,
        "near_group_count": int(summary.get("near_group_position_count") or 0) == 33,
        "interpolated_count": int(summary.get("interpolated_position_count") or 0) == 16,
        "nearest_event_count": int(summary.get("nearest_event_position_count") or 0) == 1,
        "profile_median_count": int(summary.get("profile_median_position_count") or 0) == 0,
        "animation_target_count": int(summary.get("protected_animation_target_count") or 0) == 16,
        "no_plan_failures": not plan.get("failures"),
    }
    failures.extend(key for key, passed in checks.items() if not passed)
    payload = {
        "ok": not failures,
        "step": "Major Step 3B.5A",
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
