#!/usr/bin/env python3
"""Validate Major Step 3B.6A source-fidelity audit and redetection plan."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

VERSION = "validate_caption_source_fidelity_audit_step_3B_6A_v1_0"
EXPECTED_V3_COUNT = 116


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def canonical_hash(value: Dict[str, Any]) -> str:
    clean = dict(value)
    clean.pop("audit_hash", None)
    clean.pop("plan_hash", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", required=True)
    parser.add_argument("--redetection-plan", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    failures: List[str] = []
    try:
        audit = load_json(Path(args.audit).resolve())
        plan = load_json(Path(args.redetection_plan).resolve())
    except Exception as exc:
        payload = {"ok": False, "step": "Major Step 3B.6A", "validator_version": VERSION, "failures": [f"load_failed:{type(exc).__name__}:{exc}"]}
        write_json(output, payload)
        print(json.dumps(payload, indent=2))
        return 1

    summary = audit.get("summary") or {}
    items = [x for x in (audit.get("items") or []) if isinstance(x, dict)]
    cues = {x.get("cue_id"): x for x in items}
    policy = audit.get("effect_policy") or {}
    plan_targets = [x for x in (plan.get("cue_targets") or []) if isinstance(x, dict)]
    checks = {
        "audit_ok": bool(audit.get("ok")),
        "plan_ok": bool(plan.get("ok")),
        "audit_hash": audit.get("audit_hash") == canonical_hash(audit),
        "plan_hash": plan.get("plan_hash") == canonical_hash(plan),
        "audit_step": audit.get("step") == "Major Step 3B.6A",
        "plan_schema": plan.get("schema") == "video_cloner_caption_scene_redetection_plan",
        "v3_count": len(items) == EXPECTED_V3_COUNT == int(summary.get("v3_item_count") or 0),
        "unique_cues": len({x.get("cue_id") for x in items}) == EXPECTED_V3_COUNT,
        "source_partition": int(summary.get("direct_event_source_count") or 0) + int(summary.get("classified_group_source_count") or 0) == EXPECTED_V3_COUNT,
        "not_false_exact": summary.get("current_position_plan_source_exact") is False and summary.get("current_generic_animation_source_exact") is False,
        "redetection_accounted": len(plan_targets) == int(summary.get("dense_word_instance_redetection_required_count") or 0),
        "timeline_read_only": summary.get("timeline_modified") is False,
        "hard_outline_forbidden": policy.get("hard_outline_default_forbidden") is True and policy.get("solid_outline_100pct_no_blur_forbidden") is True,
        "outline_alpha_capped": float(policy.get("outline_alpha_max") or 1.0) < 1.0,
        "soft_effect_default": policy.get("default_effect") == "centered_shadow_glow" and float(policy.get("shadow_or_glow_softness_min") or 0.0) > 0.0,
        "sub_063_contamination": cues.get("sub_063", {}).get("geometry_exactness") == "cue_instance_contaminated",
        "sub_066_contamination": cues.get("sub_066", {}).get("geometry_exactness") == "cue_instance_contaminated",
        "has_flagged_scenes": int(summary.get("flagged_scene_count") or 0) > 0,
        "no_audit_failures": not audit.get("failures"),
        "no_plan_failures": not plan.get("failures"),
    }
    failures.extend(name for name, ok in checks.items() if not ok)
    payload = {
        "ok": not failures,
        "step": "Major Step 3B.6A",
        "validator_version": VERSION,
        "audit": str(Path(args.audit).resolve()),
        "redetection_plan": str(Path(args.redetection_plan).resolve()),
        "summary": summary,
        "checks": checks,
        "warnings": audit.get("warnings") or [],
        "failures": failures,
        "output": str(output),
    }
    write_json(output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
