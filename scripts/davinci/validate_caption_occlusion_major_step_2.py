#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


VALIDATOR_VERSION = "validate_caption_occlusion_major_step_2_v1_1_accumulated_state_aware"
EXPECTED_CONTROLLER_VERSION = (
    "resolve_video_cloner_controller_v0_9_3_step_2G_major_step_2_completion_gate"
)
EXPECTED_FINALIZATION_STATUS = "technical_complete_visual_review_pending"
EXPECTED_RANGE = [429, 434]
EXPECTED_CUE = "sub_0052"
EXPECTED_PREFIX = "VC_OCCLUSION_RGBA_"

VALID_CURRENT_STATUSES = {
    "applied_rgba_sequence",
    "verified_idempotent_rgba_sequence",
}
VALID_SPAN_STATUSES = {
    "created_and_verified",
    "reused_existing_verified_item",
}


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return data


def get_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return default


def file_meta(path: Path) -> Dict[str, Any]:
    try:
        stat = path.stat()
        return {
            "path": str(path),
            "exists": True,
            "size_bytes": stat.st_size,
            "modified_unix": stat.st_mtime,
        }
    except Exception:
        return {
            "path": str(path),
            "exists": False,
            "size_bytes": None,
            "modified_unix": None,
        }


def select_span_verification(span: Dict[str, Any]) -> Dict[str, Any]:
    """
    Creation runs store final_verification.
    Reuse runs store existing_verification.
    Both are valid proof of the same exact V4 timeline item.
    """
    for key in (
        "existing_verification",
        "final_verification",
        "verification",
    ):
        value = span.get(key)
        if isinstance(value, dict):
            return value

    timeline_append = span.get("timeline_append")
    if isinstance(timeline_append, dict):
        settle = timeline_append.get("settle_verification")
        if isinstance(settle, dict):
            final = settle.get("final_verification")
            if isinstance(final, dict):
                return final

    return {}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate Major Step 2 from accumulated creation/reuse evidence. "
            "The current controller report may be either the creation run or "
            "the idempotent reuse run."
        )
    )
    parser.add_argument("--report", required=True)
    parser.add_argument("--finalization", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report_path = Path(args.report)
    finalization_path = Path(args.finalization)
    state_path = Path(args.state)
    output_path = Path(args.output)

    report = load_json(report_path)
    finalization = load_json(finalization_path)
    persistent_state = load_json(state_path)

    failures: List[str] = []
    warnings: List[str] = []

    controller_version = str(report.get("controller_version") or "")
    if controller_version != EXPECTED_CONTROLLER_VERSION:
        failures.append(f"controller_version:{controller_version!r}")
    if not report.get("ok"):
        failures.append("controller_report_ok_false")

    occ = report.get("caption_occlusion") or {}
    current_status = str(occ.get("status") or "")
    if not occ.get("ok"):
        failures.append("caption_occlusion_ok_false")
    if current_status not in VALID_CURRENT_STATUSES:
        failures.append(f"unsupported_current_status:{current_status!r}")

    requested_count = get_int(occ.get("requested_span_count"), -1)
    created_count = get_int(occ.get("created_count"), -1)
    reused_count = get_int(occ.get("reused_count"), -1)
    ready_count = get_int(occ.get("ready_count"), -1)
    failed_count = get_int(occ.get("failed_count"), -1)

    if requested_count != 1:
        failures.append(f"requested_span_count:{requested_count}")
    if ready_count != 1:
        failures.append(f"ready_count:{ready_count}")
    if failed_count != 0:
        failures.append(f"failed_count:{failed_count}")
    if created_count + reused_count != 1:
        failures.append(
            f"created_plus_reused_count:{created_count + reused_count}"
        )

    core_integrity = occ.get("core_track_integrity") or {}
    if not core_integrity.get("ok"):
        failures.append("core_track_integrity_false")

    guard = report.get("caption_dependency_guard") or {}
    if not guard.get("coverage_ok"):
        failures.append("v3_exact_coverage_false")

    spans = occ.get("spans") or []
    if len(spans) != 1:
        failures.append(f"span_count:{len(spans)}")
        span = {}
    else:
        span = spans[0]

    if span:
        span_status = str(span.get("status") or "")
        if span_status not in VALID_SPAN_STATUSES:
            failures.append(f"unsupported_span_status:{span_status!r}")

        if list(span.get("timeline_range") or []) != EXPECTED_RANGE:
            failures.append("v4_range_mismatch")

        cues = set(
            span.get("canonical_cue_ids")
            or span.get("affected_cue_ids")
            or []
        )
        if EXPECTED_CUE not in cues:
            failures.append("sub_0052_linkage_missing")

        item_name = str(span.get("item_name") or "")
        if not item_name.startswith(EXPECTED_PREFIX):
            failures.append(f"v4_item_name_prefix_wrong:{item_name!r}")

        verification = select_span_verification(span)
        if not verification:
            failures.append("v4_verification_contract_missing")
        elif not verification.get("ok"):
            failures.append("v4_verification_false")
        else:
            actual_name = str(
                verification.get("actual_name")
                or verification.get("expected_name")
                or item_name
            )
            if not actual_name.startswith(EXPECTED_PREFIX):
                failures.append(
                    f"verified_v4_name_prefix_wrong:{actual_name!r}"
                )

            range_check = verification.get("range") or verification
            actual = range_check.get("actual") or {}
            if actual:
                actual_start = get_int(actual.get("start"), -1)
                actual_end = get_int(actual.get("end"), -1)
                actual_duration = get_int(actual.get("duration"), -1)
                if actual_start != 429:
                    failures.append(f"verified_v4_start:{actual_start}")
                if actual_end != 434:
                    failures.append(f"verified_v4_end:{actual_end}")
                if actual_duration != 5:
                    failures.append(
                        f"verified_v4_duration:{actual_duration}"
                    )

    if finalization.get("controller_version") != EXPECTED_CONTROLLER_VERSION:
        failures.append("finalization_controller_version_mismatch")
    if finalization.get("status") != EXPECTED_FINALIZATION_STATUS:
        failures.append(
            f"finalization_status:{finalization.get('status')!r}"
        )
    if not finalization.get("technical_complete"):
        failures.append("finalization_technical_complete_false")

    final_checks = finalization.get("checks") or {}
    required_checks = (
        "current_occlusion_ok",
        "rgba_asset_plan_valid",
        "v3_exact_coverage_ok",
        "v1_a1_core_integrity_ok",
        "exact_requested_ready_count_ok",
        "rgba_sequence_backend_ok",
        "legacy_bbox_fallback_unused",
        "creation_pass_ok",
        "idempotency_reuse_pass_ok",
    )
    for key in required_checks:
        if final_checks.get(key) is not True:
            failures.append(f"finalization_check_false:{key}")

    accumulated = finalization.get("accumulated_state") or {}
    creation_evidence = bool(
        accumulated.get("creation_pass_ok")
        or persistent_state.get("creation_pass_ok")
    )
    reuse_evidence = bool(
        accumulated.get("idempotency_pass_ok")
        or persistent_state.get("idempotency_pass_ok")
    )
    persistent_technical_complete = bool(
        persistent_state.get("technical_complete")
    )

    if not creation_evidence:
        failures.append("creation_pass_evidence_missing")
    if not reuse_evidence:
        failures.append("idempotency_pass_evidence_missing")
    if not persistent_technical_complete:
        failures.append("persistent_state_technical_complete_false")

    # The current report can legitimately be either:
    # - the creation run, or
    # - the reuse run.
    # Accumulated state is the authoritative proof that both occurred.
    current_is_creation = bool(
        current_status == "applied_rgba_sequence"
        and created_count == 1
        and reused_count == 0
    )
    current_is_reuse = bool(
        current_status == "verified_idempotent_rgba_sequence"
        and created_count == 0
        and reused_count == 1
    )

    if not (current_is_creation or current_is_reuse):
        failures.append(
            "current_run_not_valid_creation_or_reuse_contract"
        )

    if current_is_creation and reuse_evidence:
        warnings.append(
            "Current report is the creation run, but accumulated state "
            "already contains a successful idempotent reuse pass."
        )
    if current_is_reuse and creation_evidence:
        warnings.append(
            "Current report is the reuse run and accumulated state contains "
            "the prior successful creation pass."
        )

    visual = finalization.get("visual_review") or {}
    if visual.get("required") is not True:
        failures.append("visual_review_contract_missing")
    if get_int(visual.get("review_frame"), -1) != 431:
        failures.append("visual_review_frame_mismatch")
    if list(visual.get("timeline_range") or []) != EXPECTED_RANGE:
        failures.append("visual_review_range_mismatch")
    visual_cues = set(visual.get("cue_ids") or [])
    if EXPECTED_CUE not in visual_cues:
        failures.append("visual_review_cue_missing")

    technical_complete = not failures

    result = {
        "ok": technical_complete,
        "validator_version": VALIDATOR_VERSION,
        "major_step": 2,
        "technical_pipeline_complete": technical_complete,
        "status": (
            "technical_complete_visual_review_pending"
            if technical_complete
            else "technical_validation_failed"
        ),
        "evidence_policy": (
            "accumulated_creation_and_idempotency_state_with_current_item_check"
        ),
        "manual_visual_confirmation_required": True,
        "manual_visual_confirmation_complete": False,
        "completion_percent_before_visual_confirmation": (
            95 if technical_complete else 0
        ),
        "controller_version": controller_version,
        "current_run": {
            "status": current_status,
            "kind": (
                "creation"
                if current_is_creation
                else "idempotent_reuse"
                if current_is_reuse
                else "invalid"
            ),
            "created_count": created_count,
            "reused_count": reused_count,
            "ready_count": ready_count,
            "failed_count": failed_count,
        },
        "accumulated_evidence": {
            "creation_pass_ok": creation_evidence,
            "idempotency_pass_ok": reuse_evidence,
            "persistent_technical_complete": persistent_technical_complete,
        },
        "v4": {
            "span_count": len(spans),
            "timeline_range": list(span.get("timeline_range") or []),
            "cue_ids": list(
                span.get("canonical_cue_ids")
                or span.get("affected_cue_ids")
                or []
            ),
            "item_name": span.get("item_name"),
            "span_status": span.get("status"),
        },
        "review_frame": get_int(visual.get("review_frame"), 431),
        "review_seconds": visual.get("review_seconds"),
        "review_cue": EXPECTED_CUE,
        "inputs": {
            "report": file_meta(report_path),
            "finalization": file_meta(finalization_path),
            "state": file_meta(state_path),
        },
        "warnings": warnings,
        "failures": failures,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if technical_complete:
        print(
            "PASS: Major Step 2 technical pipeline is complete. "
            "Exactly one V4 item is correct. "
            "One composed-viewer visual check remains."
        )

    return 0 if technical_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
