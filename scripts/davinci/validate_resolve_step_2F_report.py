#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

EXPECTED_VERSION = "resolve_video_cloner_controller_v0_9_2_step_2F_rgba_end_exclusive_settle_verify"
EXPECTED_MODE = "rgba_sequence_apply"
EXPECTED_SCOPE = "local_foreground_patch_intersecting_caption_region"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def get_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return default


def canonical_cue(value: Any) -> Optional[str]:
    import re
    match = re.search(r"(?i)sub[_-]?0*(\d+)", str(value or ""))
    return f"sub_{int(match.group(1)):04d}" if match else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Resolve Step 2F V4 RGBA import report.")
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--expected-span-count", type=int, default=1)
    parser.add_argument("--expected-frame-count", type=int, default=5)
    parser.add_argument("--expected-cue-id", default="sub_0052")
    parser.add_argument("--expected-start-frame", type=int, default=429)
    parser.add_argument("--expected-end-frame", type=int, default=434)
    args = parser.parse_args()

    report_path = Path(args.report)
    report = load_json(report_path)
    failures: List[str] = []

    if report.get("controller_version") != EXPECTED_VERSION:
        failures.append(f"controller_version:{report.get('controller_version')!r}")
    if not report.get("ok"):
        failures.append("controller_report_ok_false")

    guard = report.get("caption_dependency_guard") or {}
    if not guard.get("coverage_ok"):
        failures.append("v3_exact_coverage_false")

    occ = report.get("caption_occlusion") or {}
    deferred_statuses = {
        "deferred_after_v3_recovery_run",
        "blocked_after_unverified_v3_recovery",
    }
    if occ.get("status") in deferred_statuses:
        failures.append(f"step_2f_not_executed:{occ.get('status')}")
        result = {
            "ok": False,
            "controller_version": report.get("controller_version"),
            "status": occ.get("status"),
            "created_count": 0,
            "reused_count": 0,
            "ready_count": 0,
            "failed_count": get_int(occ.get("failed_count"), 0),
            "v3_coverage_ok": bool(guard.get("coverage_ok")),
            "v4_range": [args.expected_start_frame, args.expected_end_frame],
            "cue_id": canonical_cue(args.expected_cue_id),
            "needs_controller_rerun": occ.get("status") == "deferred_after_v3_recovery_run",
            "failures": failures,
        }
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("ERROR: Step 2F did not execute. Install/run controller v0.9.1; it continues after successful V3 recovery in the same Resolve run.")
        return 1

    plan = report.get("caption_occlusion_plan") or {}
    if not plan.get("contract_valid"):
        failures.append("rgba_plan_contract_invalid")
    if get_int(plan.get("span_count"), -1) != args.expected_span_count:
        failures.append("rgba_plan_span_count_mismatch")
    if get_int(plan.get("requested_frame_count"), -1) != args.expected_frame_count:
        failures.append("rgba_plan_frame_count_mismatch")

    if occ.get("mode") != EXPECTED_MODE:
        failures.append(f"occlusion_mode:{occ.get('mode')!r}")
    if not occ.get("ok"):
        failures.append("caption_occlusion_ok_false")
    if get_int(occ.get("requested_span_count"), -1) != args.expected_span_count:
        failures.append("requested_span_count_mismatch")
    if get_int(occ.get("ready_count"), -1) != args.expected_span_count:
        failures.append("ready_count_mismatch")
    if get_int(occ.get("failed_count"), -1) != 0:
        failures.append("failed_count_nonzero")
    if get_int(occ.get("created_count"), 0) + get_int(occ.get("reused_count"), 0) != args.expected_span_count:
        failures.append("created_plus_reused_count_mismatch")
    if not (occ.get("core_track_integrity") or {}).get("ok"):
        failures.append("core_track_integrity_false")
    fidelity = occ.get("fidelity") or {}
    if fidelity.get("asset_scope") != EXPECTED_SCOPE:
        failures.append("asset_scope_mismatch")
    if fidelity.get("legacy_bbox_fallback_used") is not False:
        failures.append("legacy_bbox_fallback_was_used")

    spans = occ.get("spans") or []
    if len(spans) != args.expected_span_count:
        failures.append(f"result_span_count:{len(spans)}")

    expected_cue = canonical_cue(args.expected_cue_id)
    for span in spans:
        span_id = str(span.get("span_id") or "")
        if span.get("errors"):
            failures.append(f"{span_id}:errors_present")
        if span.get("status") not in {"created_and_verified", "reused_existing_verified_item"}:
            failures.append(f"{span_id}:bad_status:{span.get('status')!r}")
        if list(span.get("timeline_range") or []) != [args.expected_start_frame, args.expected_end_frame]:
            failures.append(f"{span_id}:timeline_range_mismatch")
        cues = {canonical_cue(value) for value in (span.get("canonical_cue_ids") or span.get("affected_cue_ids") or [])}
        if expected_cue not in cues:
            failures.append(f"{span_id}:expected_cue_missing")
        dep = span.get("v3_dependency") or {}
        if not dep.get("ok"):
            failures.append(f"{span_id}:v3_dependency_false")
        if expected_cue not in set(dep.get("matched_cue_ids") or []):
            failures.append(f"{span_id}:v3_cue_not_matched")
        verification = span.get("final_verification") or span.get("existing_verification") or {}
        if not verification.get("ok"):
            failures.append(f"{span_id}:v4_item_verification_false")
        actual_range = ((verification.get("range") or {}).get("actual") or {})
        if get_int(actual_range.get("start"), -1) != args.expected_start_frame:
            failures.append(f"{span_id}:actual_start_mismatch")
        if get_int(actual_range.get("duration"), -1) != args.expected_frame_count:
            failures.append(f"{span_id}:actual_duration_mismatch")
        if not str(verification.get("actual_name") or "").startswith("VC_OCCLUSION_RGBA_"):
            failures.append(f"{span_id}:wrong_item_prefix")
        if span.get("status") == "created_and_verified":
            timeline_append = span.get("timeline_append") or {}
            if timeline_append.get("source_api_end_semantics") != "exclusive_for_rgba_sequence":
                failures.append(f"{span_id}:wrong_source_api_end_semantics")
            successful_attempts = [
                attempt for attempt in (timeline_append.get("attempts") or [])
                if (attempt.get("verification") or {}).get("ok")
            ]
            if not successful_attempts:
                failures.append(f"{span_id}:no_successful_append_attempt")
            else:
                successful = successful_attempts[-1]
                source_start = get_int(successful.get("source_start"), 0)
                source_end_api = get_int(successful.get("source_end_frame_api"), -1)
                if source_end_api - source_start != args.expected_frame_count:
                    failures.append(f"{span_id}:api_source_range_duration_mismatch")
                settle = (successful.get("verification") or {}).get("settle_verification") or {}
                if not settle.get("settled_ok"):
                    failures.append(f"{span_id}:settle_verification_false")

    summary = report.get("summary") or {}
    if get_int(summary.get("caption_occlusion_ops"), -1) != args.expected_span_count:
        failures.append("summary_ops_mismatch")
    if get_int(summary.get("caption_occlusion_failed"), -1) != 0:
        failures.append("summary_failed_nonzero")

    result = {
        "ok": not failures,
        "controller_version": report.get("controller_version"),
        "status": occ.get("status"),
        "created_count": get_int(occ.get("created_count"), 0),
        "reused_count": get_int(occ.get("reused_count"), 0),
        "ready_count": get_int(occ.get("ready_count"), 0),
        "failed_count": get_int(occ.get("failed_count"), 0),
        "v3_coverage_ok": bool(guard.get("coverage_ok")),
        "v4_range": [args.expected_start_frame, args.expected_end_frame],
        "cue_id": expected_cue,
        "failures": failures,
    }

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["ok"]:
        print("PASS: Step 2F V4 RGBA sequence placement is exact, linked, idempotent and editor-safe.")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
