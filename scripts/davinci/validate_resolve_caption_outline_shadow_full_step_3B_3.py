#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

VERSION = "validate_resolve_caption_outline_shadow_full_step_3B_3_v1_0"


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
    parser = argparse.ArgumentParser(description="Validate Major Step 3B.3B full rollout Resolve reports.")
    parser.add_argument("--mode", required=True, choices=("first_application_pass", "idempotent_second_run"))
    parser.add_argument("--plan", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-v3-count", type=int, default=116)
    parser.add_argument("--expected-rollout-target-count", type=int, default=113)
    parser.add_argument("--expected-disabled-count", type=int, default=3)
    args = parser.parse_args()

    plan_path = Path(args.plan)
    report_path = Path(args.report)
    output_path = Path(args.output)
    plan = load_json(plan_path)
    report = load_json(report_path)
    summary = report.get("summary") or {}
    plan_summary = plan.get("summary") or {}
    items = [row for row in (report.get("items") or []) if isinstance(row, dict)]
    expected_v3 = int(args.expected_v3_count)
    expected_targets = int(args.expected_rollout_target_count)
    expected_disabled = int(args.expected_disabled_count)
    expected_outline = integer(plan_summary, "outline_enabled_count")
    expected_shadow = integer(plan_summary, "shadow_enabled_count")
    expected_report_mode = "first_application" if args.mode == "first_application_pass" else "idempotent_second_run"

    checks = {
        "plan_ok": bool(plan.get("ok")),
        "plan_hash_valid": plan.get("plan_hash") == canonical_hash(plan),
        "report_ok": bool(report.get("ok")),
        "workspace_version": str(report.get("workspace_version") or "").startswith("resolve_caption_outline_shadow_step_3B_3B_"),
        "report_run_mode": report.get("run_mode") == expected_report_mode,
        "plan_hash_match": report.get("plan_hash") == plan.get("plan_hash"),
        "v3_candidate_count": integer(summary, "v3_candidate_count") == expected_v3,
        "plan_item_count": integer(summary, "plan_item_count") == expected_v3,
        "rollout_target_count": integer(summary, "rollout_target_count") == expected_targets,
        "disabled_plan_count": integer(summary, "disabled_plan_count") == expected_disabled,
        "mapped_count": integer(summary, "mapped_count") == expected_v3,
        "accepted_probe_already_correct": integer(summary, "accepted_probe_already_correct_count") == 1,
        "outline_requested_count": integer(summary, "outline_requested_count") == expected_outline,
        "outline_verified_count": integer(summary, "outline_verified_count") == expected_outline,
        "shadow_requested_count": integer(summary, "shadow_requested_count") == expected_shadow,
        "shadow_verified_count": integer(summary, "shadow_verified_count") == expected_shadow,
        "required_inputs_all_verified": integer(summary, "required_input_count") > 0 and integer(summary, "verified_required_input_count") == integer(summary, "required_input_count"),
        "optional_inputs_all_verified": integer(summary, "optional_input_count") > 0 and integer(summary, "verified_optional_input_count") == integer(summary, "optional_input_count"),
        "selector_elements_all_verified": integer(summary, "selector_element_count") == expected_outline + expected_shadow and integer(summary, "selector_verified_count") == integer(summary, "selector_element_count"),
        "protected_caption_count": integer(summary, "protected_caption_count") == expected_v3,
        "protected_caption_verified_count": integer(summary, "protected_caption_verified_count") == expected_v3,
        "protected_animation_target_count": integer(summary, "protected_animation_target_count") == 16,
        "protected_animation_verified_count": integer(summary, "protected_animation_verified_count") == 16,
        "disabled_untouched_count": integer(summary, "disabled_untouched_count") == expected_disabled,
        "identity_integrity_failure_count": integer(summary, "identity_integrity_failure_count") == 0,
        "fill_integrity_failure_count": integer(summary, "fill_integrity_failure_count") == 0,
        "layout_integrity_failure_count": integer(summary, "layout_integrity_failure_count") == 0,
        "animation_integrity_failure_count": integer(summary, "animation_integrity_failure_count") == 0,
        "timeline_integrity_failure_count": integer(summary, "timeline_integrity_failure_count") == 0,
        "rollback_not_performed": integer(summary, "rollback_performed_count") == 0,
        "failed_item_count": integer(summary, "failed_item_count") == 0,
        "failed_count": integer(summary, "failed_count") == 0,
        "report_item_count": len(items) == expected_targets,
        "all_item_readbacks": len(items) == expected_targets and all(row.get("persistent_readback_ok") for row in items),
        "all_item_protected_integrity": len(items) == expected_targets and all(row.get("protected_integrity_ok") for row in items),
        "disabled_report": integer(report.get("disabled_items") or {}, "expected_count") == expected_disabled and integer(report.get("disabled_items") or {}, "untouched_count") == expected_disabled and not ((report.get("disabled_items") or {}).get("changed_names") or []),
        "track_integrity": bool((report.get("track_integrity") or {}).get("ok")),
        "v3_track_integrity": bool((report.get("v3_track_integrity") or {}).get("ok")),
        "no_report_failures": not (report.get("failures") or []),
        "known_visual_debt_declared": bool(report.get("known_visual_debt")),
    }

    if args.mode == "first_application_pass":
        checks.update({
            "first_run_modified_count": integer(summary, "modified_count") == expected_targets - 1,
            "first_run_already_correct_count": integer(summary, "already_correct_count") == 1,
            "first_run_item_modified_count": sum(bool(row.get("modified")) for row in items) == expected_targets - 1,
        })
    else:
        checks.update({
            "second_run_modified_count": integer(summary, "modified_count") == 0,
            "second_run_already_correct_count": integer(summary, "already_correct_count") == expected_targets,
            "second_run_no_item_modified": not any(row.get("modified") for row in items),
        })

    failures: List[str] = [key for key, value in checks.items() if not value]
    warnings: List[str] = list(report.get("warnings") or [])
    validation = {
        "ok": not failures,
        "step": "Major Step 3B.3B",
        "validator_version": VERSION,
        "mode": args.mode,
        "plan": str(plan_path),
        "report": str(report_path),
        "summary": summary,
        "checks": checks,
        "warnings": warnings,
        "failures": failures,
        "output": str(output_path),
    }
    write_json(output_path, validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    return 0 if validation["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
