#!/usr/bin/env python3
"""Fail-closed gate for immutable Step 3B.6C first-pass/idempotency evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Sequence

VERSION = "validate_caption_source_geometry_probe_evidence_step_3B_6C_v1_1_canonical_readback"
PLAN_SCHEMA = "video_cloner_caption_source_geometry_probe_plan"
REPORT_VALIDATOR_VERSION = "validate_resolve_caption_source_geometry_probe_step_3B_6C_v1_0"
ACCEPTED_IDEMPOTENCY_TASK_ID = "DZSQH7AUHJT_STEP_3B_6C_IDEMPOTENCY_EVIDENCE_REGENERATION_V1"
ACCEPTED_IDEMPOTENCY_RUN_ID = "20260802T132415124Z_adb873fd4d154b25a99fd4efce8b6e7f"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: Dict[str, Any], ignored: Sequence[str] = ()) -> str:
    clean = dict(value)
    clean.pop("plan_hash", None)
    for key in ignored:
        clean.pop(key, None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def same_path(reference: Any, expected: Path) -> bool:
    if not isinstance(reference, str) or not reference:
        return False
    return Path(reference).resolve() == expected.resolve()


def integer(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_summary(summary: Dict[str, Any]) -> bool:
    return all(
        (
            int(summary.get("non_probe_caption_count") or 0) == 115,
            int(summary.get("non_probe_caption_verified_count") or 0) == 115,
            int(summary.get("protected_animation_caption_count") or 0) == 8,
            int(summary.get("protected_animation_verified_count") or 0) == 8,
            int(summary.get("protected_animation_target_count") or 0) == 16,
            int(summary.get("protected_animation_target_verified_count") or 0) == 16,
            int(summary.get("opacity_proxy_applied_count") or 0) == 0,
            int(summary.get("z_order_write_count") or 0) == 0,
            int(summary.get("timeline_boundary_write_count") or 0) == 0,
            int(summary.get("timeline_integrity_failure_count") or 0) == 0,
            int(summary.get("protected_integrity_failure_count") or 0) == 0,
            int(summary.get("failed_count") or 0) == 0,
        )
    )


def assess_pair(
    plan_path: Path,
    plan_hash: str,
    report_path: Path,
    validation_path: Path,
    report_mode: str,
    validation_mode: str,
    expected_task_id: str | None = None,
    expected_run_id: str | None = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "report_path": str(report_path.resolve()),
        "validation_path": str(validation_path.resolve()),
        "report_exists": report_path.is_file(),
        "validation_exists": validation_path.is_file(),
    }
    if not result["report_exists"] or not result["validation_exists"]:
        result["accepted"] = False
        result["failures"] = [name for name in ("report_missing", "validation_missing") if not result[name.replace("_missing", "_exists")]]
        return result

    report = load_json(report_path)
    validation = load_json(validation_path)
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    validation_checks = validation.get("checks") if isinstance(validation.get("checks"), dict) else {}
    expected_modified = 1 if report_mode == "first_application" else 0
    expected_already_correct = 0 if report_mode == "first_application" else 1
    checks = {
        "report_ok": bool(report.get("ok")),
        "report_mode": report.get("run_mode") == report_mode,
        "report_plan_hash": report.get("plan_hash") == plan_hash,
        "report_no_failures": not report.get("failures"),
        "expected_modified_count": int(summary.get("modified_count") or 0) == expected_modified,
        "expected_already_correct_count": int(summary.get("already_correct_count") or 0) == expected_already_correct,
        "protected_state": safe_summary(summary),
        "track_integrity": bool((report.get("track_integrity") or {}).get("ok")),
        "v3_track_integrity": bool((report.get("v3_track_integrity") or {}).get("ok")),
        "validation_ok": bool(validation.get("ok")),
        "validation_version": validation.get("validator_version") == REPORT_VALIDATOR_VERSION,
        "validation_mode": validation.get("mode") == validation_mode,
        "validation_no_failures": not validation.get("failures"),
        "validation_checks_present": bool(validation_checks),
        "validation_checks_all_true": bool(validation_checks) and all(value is True for value in validation_checks.values()),
        "validation_plan_path": same_path(validation.get("plan"), plan_path),
        "validation_report_path": same_path(validation.get("report"), report_path),
    }
    if expected_task_id is not None and expected_run_id is not None:
        checks.update(
            {
                "report_task_id": report.get("task_id") == expected_task_id,
                "report_run_id": report.get("run_id") == expected_run_id,
                "validation_task_id": validation.get("task_id") == expected_task_id,
                "validation_run_id": validation.get("run_id") == expected_run_id,
                "timeline_unmodified": report.get("timeline_modified") is False,
                "zero_setter_calls": integer(report.get("setter_call_count")) == 0,
                "zero_effective_mutations": integer(report.get("effective_mutation_count")) == 0,
                "zero_blend_operations": integer(report.get("blend_operation_count")) == 0,
            }
        )
    failures = [name for name, ok in checks.items() if not ok]
    result.update(
        {
            "report_sha256": sha256(report_path),
            "validation_sha256": sha256(validation_path),
            "checks": checks,
            "failures": failures,
            "accepted": not failures,
        }
    )
    return result


def assess(
    plan_path: Path,
    first_report_path: Path,
    first_validation_path: Path,
    idempotency_report_path: Path,
    idempotency_validation_path: Path,
) -> Dict[str, Any]:
    plan = load_json(plan_path)
    expected_hash = canonical_hash(plan, ignored=("created_at_unix",))
    plan_checks = {
        "ok": bool(plan.get("ok")),
        "schema": plan.get("schema") == PLAN_SCHEMA,
        "hash": plan.get("plan_hash") == expected_hash,
    }
    first = assess_pair(
        plan_path,
        expected_hash,
        first_report_path,
        first_validation_path,
        "first_application",
        "first_application_pass",
    )
    idempotency = assess_pair(
        plan_path,
        expected_hash,
        idempotency_report_path,
        idempotency_validation_path,
        "idempotent_second_run",
        "idempotent_second_run",
        ACCEPTED_IDEMPOTENCY_TASK_ID,
        ACCEPTED_IDEMPOTENCY_RUN_ID,
    )
    idempotency_report = load_json(idempotency_report_path) if idempotency_report_path.is_file() else {}
    historical_binding = first_report_path.is_file() and same_path(idempotency_report.get("first_report_path"), first_report_path)
    first["required_for_acceptance"] = False
    idempotency["required_for_acceptance"] = True
    accepted = all(plan_checks.values()) and historical_binding and bool(idempotency.get("accepted"))
    return {
        "ok": accepted,
        "accepted": accepted,
        "next_step_permitted": accepted,
        "step": "Major Step 3B.6C evidence gate",
        "validator_version": VERSION,
        "plan_path": str(plan_path.resolve()),
        "plan_sha256": sha256(plan_path),
        "plan_hash": expected_hash,
        "plan_checks": plan_checks,
        "first_application": first,
        "idempotency": idempotency,
        "historical_first_report_binding": historical_binding,
        "acceptance_policy": "canonical_idempotency_readback_required; historical_first_application_audited_only",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--first-report", required=True, type=Path)
    parser.add_argument("--first-validation", required=True, type=Path)
    parser.add_argument("--idempotency-report", required=True, type=Path)
    parser.add_argument("--idempotency-validation", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    try:
        payload = assess(
            args.plan.resolve(),
            args.first_report.resolve(),
            args.first_validation.resolve(),
            args.idempotency_report.resolve(),
            args.idempotency_validation.resolve(),
        )
    except Exception as exc:
        payload = {
            "ok": False,
            "accepted": False,
            "next_step_permitted": False,
            "step": "Major Step 3B.6C evidence gate",
            "validator_version": VERSION,
            "failures": ["validator_exception"],
            "exception": f"{type(exc).__name__}: {exc}",
        }
    payload["output"] = str(output)
    write_json(output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("accepted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
