#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

VERSION = "validate_resolve_caption_font_step_3B_1_v1_0"


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

    controller_version = str(report.get("version") or "")
    if not controller_version.startswith("resolve_caption_font_step_3B_1_"):
        failures.append("wrong_or_missing_controller_version")

    if report.get("status") == "blocked_before_writes":
        failures.append("application_blocked_before_writes")

    if not report.get("ok"):
        failures.append("report_ok_false")

    checks = {
        "expected_v3_count": integer(report, "expected_v3_count") == expected,
        "v3_candidate_count": integer(report, "v3_candidate_count") == expected,
        "mapped_count": integer(report, "mapped_count") == expected,
        "readback_success_count": integer(report, "readback_success_count") == expected,
        "failed_count": integer(report, "failed_count") == 0,
        "preserved_input_failure_count": integer(report, "preserved_input_failure_count") == 0,
        "primary_fallback_count": integer(report, "primary_fallback_count") == 0,
        "created_count": integer(report, "created_count") == 0,
        "core_track_integrity": bool((report.get("core_track_integrity") or {}).get("ok")),
        "preflight": bool((report.get("preflight") or {}).get("ok")),
        "mapping_profiles_present": integer(report, "mapping_profile_count") > 0,
    }

    for key, passed in checks.items():
        if not passed:
            failures.append(f"check_failed:{key}")

    modified = integer(report, "modified_count")
    already = integer(report, "already_correct_count")
    if modified + already != expected:
        failures.append("modified_plus_already_correct_count_mismatch")

    if args.require_idempotent:
        if modified != 0:
            failures.append("second_run_modified_count_not_zero")
        if already != expected:
            failures.append("second_run_already_correct_count_not_expected")
        expected_status = "idempotent_second_run"
    else:
        expected_status = "first_application_pass"
        if modified == 0 and already == expected:
            warnings.append("Timeline was already correctly mapped before this validation run.")

    validation = {
        "ok": len(failures) == 0,
        "step": "Major Step 3B.1",
        "validator_version": VERSION,
        "mode": expected_status,
        "report": str(report_path),
        "expected_v3_count": expected,
        "summary": {
            "v3_candidate_count": integer(report, "v3_candidate_count"),
            "mapped_count": integer(report, "mapped_count"),
            "modified_count": modified,
            "already_correct_count": already,
            "readback_success_count": integer(report, "readback_success_count"),
            "failed_count": integer(report, "failed_count"),
            "preserved_input_failure_count": integer(report, "preserved_input_failure_count"),
            "primary_fallback_count": integer(report, "primary_fallback_count"),
            "mapping_profile_count": integer(report, "mapping_profile_count"),
            "profile_item_counts": report.get("profile_item_counts") or {},
        },
        "checks": checks,
        "warnings": warnings,
        "failures": failures,
    }
    write_json(output_path, validation)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    if validation["ok"]:
        if args.require_idempotent:
            print("PASS: Step 3B.1 second run is idempotent; all 116 V3 Text+ fonts were reused without writes.")
        else:
            print("PASS: Step 3B.1 applied and read back the approved font mapping on all 116 V3 Text+ items.")
        return 0
    print("ERROR: Step 3B.1 validation failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
