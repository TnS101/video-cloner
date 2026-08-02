#!/usr/bin/env python3
"""Validate Major Step 3B.4A Resolve first/idempotent reports."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict

VERSION = "validate_resolve_caption_fill_color_probe_step_3B_4_v1_0"


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


def canonical_hash(payload: Dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("plan_hash", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--mode", required=True, choices=("first_application_pass", "idempotent_second_run"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-v3-count", type=int, default=116)
    parser.add_argument("--probe-cue-id", default="sub_019")
    args = parser.parse_args()

    plan_path = Path(args.plan).resolve()
    report_path = Path(args.report).resolve()
    try:
        plan = load_json(plan_path)
        report = load_json(report_path)
        summary = report.get("summary") or {}
        expected_run_mode = "first_application" if args.mode == "first_application_pass" else "idempotent_second_run"
        checks = {
            "plan_ok": plan.get("ok") is True,
            "plan_hash_valid": plan.get("plan_hash") == canonical_hash(plan),
            "report_ok": report.get("ok") is True,
            "workspace_version": report.get("workspace_version") == "resolve_caption_fill_color_step_3B_4A_v1_0_detected_fill_probe",
            "report_run_mode": report.get("run_mode") == expected_run_mode,
            "plan_hash_match": report.get("plan_hash") == plan.get("plan_hash"),
            "probe_cue_id": report.get("probe_cue_id") == args.probe_cue_id,
            "v3_candidate_count": int(summary.get("v3_candidate_count") or 0) == args.expected_v3_count,
            "probe_item_count": int(summary.get("probe_item_count") or 0) == 1,
            "mapped_count": int(summary.get("mapped_count") or 0) == 1,
            "fill_requested_count": int(summary.get("fill_requested_count") or 0) == 1,
            "fill_verified_count": int(summary.get("fill_verified_count") or 0) == 1,
            "outline_shadow_preserved": int(summary.get("protected_outline_shadow_verified_count") or 0) == 2,
            "animation_target_count": int(summary.get("protected_animation_target_count") or 0) == 2,
            "animation_targets_preserved": int(summary.get("protected_animation_verified_count") or 0) == 2,
            "identity_integrity": int(summary.get("identity_integrity_failure_count") or 0) == 0,
            "layout_integrity": int(summary.get("layout_integrity_failure_count") or 0) == 0,
            "outline_shadow_integrity": int(summary.get("outline_shadow_integrity_failure_count") or 0) == 0,
            "animation_integrity": int(summary.get("animation_integrity_failure_count") or 0) == 0,
            "timeline_integrity": int(summary.get("timeline_integrity_failure_count") or 0) == 0,
            "rollback_not_performed": int(summary.get("rollback_performed_count") or 0) == 0,
            "failed_count": int(summary.get("failed_count") or 0) == 0,
            "persistent_readback": report.get("persistent_readback_ok") is True,
            "protected_integrity": (report.get("protected_integrity") or {}).get("ok") is True,
            "track_integrity": (report.get("track_integrity") or {}).get("ok") is True,
            "v3_track_integrity": (report.get("v3_track_integrity") or {}).get("ok") is True,
            "no_report_failures": not (report.get("failures") or []),
        }
        if args.mode == "first_application_pass":
            checks.update({
                "first_run_modified_count": int(summary.get("modified_count") or 0) == 1,
                "first_run_already_correct_count": int(summary.get("already_correct_count") or 0) == 0,
            })
        else:
            checks.update({
                "second_run_modified_count": int(summary.get("modified_count") or 0) == 0,
                "second_run_already_correct_count": int(summary.get("already_correct_count") or 0) == 1,
            })
        failures = [key for key, value in checks.items() if not value]
        result = {
            "ok": not failures,
            "step": "Major Step 3B.4A",
            "validator_version": VERSION,
            "mode": args.mode,
            "plan": str(plan_path),
            "report": str(report_path),
            "probe_cue_id": args.probe_cue_id,
            "summary": summary,
            "checks": checks,
            "warnings": report.get("warnings") or [],
            "failures": failures,
            "output": str(Path(args.output).resolve()),
        }
    except Exception as exc:
        result = {
            "ok": False,
            "step": "Major Step 3B.4A",
            "validator_version": VERSION,
            "mode": args.mode,
            "plan": str(plan_path),
            "report": str(report_path),
            "checks": {},
            "failures": [f"{type(exc).__name__}: {exc}"],
            "output": str(Path(args.output).resolve()),
        }
    write_json(Path(args.output), result)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
