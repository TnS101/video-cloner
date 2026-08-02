#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

VERSION = "validate_caption_outline_shadow_full_plan_step_3B_3_v1_0"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def canonical_hash(payload: Dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("plan_hash", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def integer(payload: Dict[str, Any], key: str) -> int:
    try:
        return int(payload.get(key) or 0)
    except Exception:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Major Step 3B.3B full rollout plan.")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-v3-count", type=int, default=116)
    parser.add_argument("--expected-rollout-target-count", type=int, default=113)
    parser.add_argument("--accepted-probe-cue-id", default="sub_019")
    args = parser.parse_args()

    plan_path = Path(args.plan)
    output_path = Path(args.output)
    plan = load_json(plan_path)
    items = [row for row in (plan.get("items") or []) if isinstance(row, dict)]
    summary = plan.get("summary") or {}
    expected = int(args.expected_v3_count)
    expected_targets = int(args.expected_rollout_target_count)
    targets = [row for row in items if row.get("rollout_selected")]
    disabled = [row for row in items if not row.get("rollout_selected")]
    accepted = [row for row in items if row.get("accepted_probe")]
    names = [str(row.get("name") or "") for row in items]
    cues = [str(row.get("cue_id") or "") for row in items]
    animation_targets = sum(len(row.get("protected_animation_targets") or []) for row in items)
    animated_captions = sum(bool(row.get("protected_animation_targets")) for row in items)

    checks = {
        "plan_ok": bool(plan.get("ok")),
        "plan_hash_valid": plan.get("plan_hash") == canonical_hash(plan),
        "schema": plan.get("schema") == "video_cloner_caption_outline_shadow_full_rollout_plan",
        "schema_version": str(plan.get("schema_version")) == "2.0",
        "step": plan.get("step") == "Major Step 3B.3B",
        "mode": plan.get("mode") == "full_v3_rollout_from_accepted_probe",
        "expected_v3_count": integer(plan, "expected_v3_count") == expected,
        "expected_rollout_target_count": integer(plan, "expected_rollout_target_count") == expected_targets,
        "item_count": len(items) == expected and integer(summary, "v3_item_count") == expected,
        "unique_names": len(set(names)) == expected and all(names),
        "unique_cues": len(set(cues)) == expected and all(cues),
        "profile_count": integer(summary, "profile_count") == 4,
        "target_count": len(targets) == expected_targets and integer(summary, "rollout_target_count") == expected_targets,
        "disabled_count": len(disabled) == expected - expected_targets and integer(summary, "disabled_both_count") == expected - expected_targets,
        "outline_count": integer(summary, "outline_enabled_count") == expected_targets,
        "shadow_count": integer(summary, "shadow_enabled_count") == expected_targets,
        "accepted_probe": len(accepted) == 1 and accepted[0].get("cue_id") == args.accepted_probe_cue_id and accepted[0].get("rollout_selected"),
        "animated_caption_count": animated_captions == 8 and integer(summary, "animated_caption_protection_count") == 8,
        "animation_target_count": animation_targets == 16 and integer(summary, "protected_animation_target_count") == 16,
        "targets_have_effect": all(
            bool((row.get("source_effect") or {}).get("outline", {}).get("enabled"))
            or bool((row.get("source_effect") or {}).get("shadow", {}).get("enabled"))
            for row in targets
        ),
        "disabled_have_no_effect": all(
            not bool((row.get("source_effect") or {}).get("outline", {}).get("enabled"))
            and not bool((row.get("source_effect") or {}).get("shadow", {}).get("enabled"))
            for row in disabled
        ),
        "no_plan_failures": not (plan.get("failures") or []),
        "known_visual_debt_declared": (plan.get("known_visual_debt") or {}).get("fill_color_fidelity") == "deferred",
    }
    failures: List[str] = [key for key, value in checks.items() if not value]
    validation = {
        "ok": not failures,
        "step": "Major Step 3B.3B",
        "validator_version": VERSION,
        "plan": str(plan_path),
        "plan_hash": plan.get("plan_hash"),
        "summary": summary,
        "checks": checks,
        "warnings": list(plan.get("warnings") or []),
        "failures": failures,
        "output": str(output_path),
    }
    write_json(output_path, validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    return 0 if validation["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
