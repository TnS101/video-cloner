#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

VERSION = "validate_resolve_caption_outline_shadow_probe_step_3B_3_v1_3_direct_slot_materialization"


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
    parser = argparse.ArgumentParser(description="Validate Major Step 3B.3A Resolve probe reports.")
    parser.add_argument("--mode", required=True, choices=("first_application_pass", "idempotent_second_run"))
    parser.add_argument("--plan", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-v3-count", type=int, default=116)
    parser.add_argument("--probe-cue-id", default="sub_019")
    args = parser.parse_args()

    plan_path = Path(args.plan)
    report_path = Path(args.report)
    output_path = Path(args.output)
    plan = load_json(plan_path)
    report = load_json(report_path)
    summary = report.get("summary") or {}
    probe = report.get("probe") or {}
    protected = probe.get("protected_integrity") or {}
    expected = int(args.expected_v3_count)
    failures: List[str] = []
    warnings: List[str] = list(report.get("warnings") or [])

    expected_report_mode = "first_application" if args.mode == "first_application_pass" else "idempotent_second_run"
    checks = {
        "plan_ok": bool(plan.get("ok")),
        "plan_hash_valid": plan.get("plan_hash") == canonical_hash(plan),
        "report_ok": bool(report.get("ok")),
        "workspace_version": str(report.get("workspace_version") or "").startswith("resolve_caption_outline_shadow_step_3B_3A_"),
        "report_run_mode": report.get("run_mode") == expected_report_mode,
        "plan_hash_match": report.get("plan_hash") == plan.get("plan_hash"),
        "probe_cue_id": report.get("probe_cue_id") == args.probe_cue_id and probe.get("cue_id") == args.probe_cue_id,
        "v3_candidate_count": integer(summary, "v3_candidate_count") == expected,
        "plan_item_count": integer(summary, "plan_item_count") == expected,
        "probe_item_count": integer(summary, "probe_item_count") == 1,
        "mapped_count": integer(summary, "mapped_count") == 1,
        "outline_requested_count": integer(summary, "outline_requested_count") == 1,
        "outline_verified_count": integer(summary, "outline_verified_count") == 1,
        "shadow_requested_count": integer(summary, "shadow_requested_count") == 1,
        "shadow_verified_count": integer(summary, "shadow_verified_count") == 1,
        "required_inputs_all_verified": integer(summary, "required_input_count") > 0 and integer(summary, "verified_required_input_count") == integer(summary, "required_input_count"),
        "selector_element_count": integer(summary, "selector_element_count") == 2,
        "selector_verified_count": integer(summary, "selector_verified_count") == 2,
        "protected_animation_target_count": integer(summary, "protected_animation_target_count") == 2,
        "protected_animation_verified_count": integer(summary, "protected_animation_verified_count") == 2,
        "identity_integrity_failure_count": integer(summary, "identity_integrity_failure_count") == 0,
        "fill_integrity_failure_count": integer(summary, "fill_integrity_failure_count") == 0,
        "layout_integrity_failure_count": integer(summary, "layout_integrity_failure_count") == 0,
        "animation_integrity_failure_count": integer(summary, "animation_integrity_failure_count") == 0,
        "timeline_integrity_failure_count": integer(summary, "timeline_integrity_failure_count") == 0,
        "rollback_not_performed": integer(summary, "rollback_performed_count") == 0,
        "failed_count": integer(summary, "failed_count") == 0,
        "persistent_readback": bool(probe.get("persistent_readback_ok")),
        "protected_integrity": bool(protected.get("ok")),
        "track_integrity": bool((report.get("track_integrity") or {}).get("ok")),
        "v3_track_integrity": bool((report.get("v3_track_integrity") or {}).get("ok")),
        "no_report_failures": not (report.get("failures") or []),
    }

    if args.mode == "first_application_pass":
        checks.update({
            "first_run_modified_count": integer(summary, "modified_count") == 1,
            "first_run_already_correct_count": integer(summary, "already_correct_count") == 0,
        })
    else:
        checks.update({
            "second_run_modified_count": integer(summary, "modified_count") == 0,
            "second_run_already_correct_count": integer(summary, "already_correct_count") == 1,
        })

    for key, passed in checks.items():
        if not passed:
            failures.append(key)

    optional_count = integer(summary, "optional_input_count")
    optional_verified = integer(summary, "verified_optional_input_count")
    core_geometry_ok = bool(
        checks.get("outline_verified_count")
        and checks.get("shadow_verified_count")
        and checks.get("required_inputs_all_verified")
        and checks.get("persistent_readback")
    )
    if core_geometry_ok and optional_verified < optional_count:
        warnings.append(
            f"Only {optional_verified}/{optional_count} optional softness/outside-only inputs were verified. "
            "Core outline and shadow geometry passed; visual review remains mandatory."
        )

    validation = {
        "ok": not failures,
        "step": "Major Step 3B.3A",
        "validator_version": VERSION,
        "mode": args.mode,
        "plan": str(plan_path),
        "report": str(report_path),
        "probe_cue_id": args.probe_cue_id,
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
