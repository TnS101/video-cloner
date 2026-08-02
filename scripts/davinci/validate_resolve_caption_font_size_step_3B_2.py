#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

VERSION = "validate_resolve_caption_font_size_step_3B_2_v1_0"


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


def integer(payload: Dict[str, Any], key: str) -> int:
    try:
        return int(payload.get(key) or 0)
    except Exception:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-v3-count", type=int, default=116)
    parser.add_argument("--require-idempotent", action="store_true")
    args = parser.parse_args()

    report_path = Path(args.report)
    output_path = Path(args.output)
    report = load_json(report_path)
    expected = int(args.expected_v3_count)
    failures = []
    warnings = []

    if not str(report.get("version") or "").startswith("resolve_caption_font_size_step_3B_2_"):
        failures.append("wrong_or_missing_controller_version")
    if not report.get("ok"):
        failures.append("report_ok_false")
    if report.get("status") == "blocked_before_writes":
        failures.append("application_blocked_before_writes")

    checks = {
        "expected_v3_count": integer(report, "expected_v3_count") == expected,
        "v3_candidate_count": integer(report, "v3_candidate_count") == expected,
        "plan_item_count": integer(report, "plan_item_count") == expected,
        "mapped_count": integer(report, "mapped_count") == expected,
        "readback_success_count": integer(report, "readback_success_count") == expected,
        "failed_count": integer(report, "failed_count") == 0,
        "preserved_input_failure_count": integer(report, "preserved_input_failure_count") == 0,
        "font_integrity_failure_count": integer(report, "font_integrity_failure_count") == 0,
        "stale_baseline_count": integer(report, "stale_baseline_count") == 0,
        "size_keyframe_input_count": integer(report, "size_keyframe_input_count") == 0,
        "core_track_integrity": bool((report.get("core_track_integrity") or {}).get("ok")),
        "preflight": bool((report.get("preflight") or {}).get("ok")),
        "profile_calibration_present": len(report.get("profile_calibration") or {}) == 4,
    }
    for key, passed in checks.items():
        if not passed:
            failures.append(f"check_failed:{key}")

    modified = integer(report, "modified_count")
    already = integer(report, "already_correct_count")
    if modified + already != expected:
        failures.append("modified_plus_already_correct_count_mismatch")

    if args.require_idempotent:
        mode = "idempotent_second_run"
        if modified != 0:
            failures.append("second_run_modified_count_not_zero")
        if already != expected:
            failures.append("second_run_already_correct_count_not_expected")
    else:
        mode = "first_application_pass"
        if modified == 0 and already == expected:
            warnings.append("Timeline already had the calibrated sizes before this validation run.")

    validation = {
        "ok": len(failures) == 0,
        "step": "Major Step 3B.2",
        "validator_version": VERSION,
        "mode": mode,
        "report": str(report_path),
        "expected_v3_count": expected,
        "summary": {
            "v3_candidate_count": integer(report, "v3_candidate_count"),
            "plan_item_count": integer(report, "plan_item_count"),
            "mapped_count": integer(report, "mapped_count"),
            "modified_count": modified,
            "already_correct_count": already,
            "readback_success_count": integer(report, "readback_success_count"),
            "failed_count": integer(report, "failed_count"),
            "preserved_input_failure_count": integer(report, "preserved_input_failure_count"),
            "font_integrity_failure_count": integer(report, "font_integrity_failure_count"),
            "stale_baseline_count": integer(report, "stale_baseline_count"),
            "profile_calibration": report.get("profile_calibration") or {},
            "visual_review_samples": report.get("visual_review_samples") or [],
        },
        "checks": checks,
        "warnings": warnings,
        "failures": failures,
    }
    write_json(output_path, validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    if validation["ok"]:
        if args.require_idempotent:
            print("PASS: Step 3B.2 second run is idempotent; all 116 calibrated sizes were reused without writes.")
        else:
            print("PASS: Step 3B.2 applied and read back the font-aware size calibration on all 116 V3 Text+ items.")
        return 0
    print("ERROR: Step 3B.2 validation failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
