#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

import cv2


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate full caption-occlusion debug-frame coverage and file integrity."
    )
    parser.add_argument("--report", required=True, help="Path to *_caption_occlusion.json")
    parser.add_argument("--require-analysis-version", default="caption_occlusion_v1_7_full_debug_coverage_validation")
    args = parser.parse_args()

    report = load_json(args.report)
    failures: List[str] = []

    version = str(report.get("analysis_version") or "")
    if args.require_analysis_version and version != args.require_analysis_version:
        failures.append(
            f"analysis_version_mismatch: expected={args.require_analysis_version!r}, actual={version!r}"
        )

    events = report.get("occlusion_events")
    if not isinstance(events, list) or not events:
        failures.append("occlusion_events_missing_or_empty")
        events = []

    successful_samples = 0
    failed_samples = 0
    referenced_paths = 0
    existing_paths = 0
    readable_paths = 0
    timestamps: List[float] = []
    events_with_success = set()
    events_with_debug = set()
    missing_paths: List[str] = []
    unreadable_paths: List[str] = []
    samples_without_debug: List[Dict[str, Any]] = []

    for event in events:
        event_index = int(event.get("index") or 0)
        samples = event.get("samples") if isinstance(event.get("samples"), list) else []
        for sample_index, sample in enumerate(samples, start=1):
            if not isinstance(sample, dict) or not sample.get("ok"):
                failed_samples += 1
                continue
            successful_samples += 1
            events_with_success.add(event_index)

            path = sample.get("debug_frame")
            if not path:
                samples_without_debug.append({
                    "event_index": event_index,
                    "sample_index": sample_index,
                    "timestamp": sample.get("timestamp"),
                    "skip_reason": sample.get("debug_frame_skipped"),
                })
                continue

            path = str(path)
            referenced_paths += 1
            events_with_debug.add(event_index)
            try:
                timestamps.append(float(sample.get("timestamp")))
            except Exception:
                pass

            if not os.path.isfile(path):
                missing_paths.append(path)
                continue
            existing_paths += 1

            image = cv2.imread(path, cv2.IMREAD_COLOR)
            if image is None or image.size == 0:
                unreadable_paths.append(path)
            else:
                readable_paths += 1

    debug_artifacts = report.get("debug_artifacts") or {}
    report_claims_complete = bool(debug_artifacts.get("complete"))

    if successful_samples <= 0:
        failures.append("zero_successful_samples")
    if referenced_paths != successful_samples:
        failures.append(
            f"incomplete_sample_coverage: successful={successful_samples}, referenced={referenced_paths}"
        )
    if events_with_debug != events_with_success:
        failures.append(
            f"incomplete_event_coverage: successful_events={len(events_with_success)}, debug_events={len(events_with_debug)}"
        )
    if missing_paths:
        failures.append(f"missing_debug_files={len(missing_paths)}")
    if unreadable_paths:
        failures.append(f"unreadable_debug_files={len(unreadable_paths)}")
    if not report_claims_complete:
        failures.append("report_debug_artifacts_complete_is_false")

    result = {
        "ok": not failures,
        "analysis_version": version,
        "events_total": len(events),
        "successful_events": len(events_with_success),
        "events_with_debug": len(events_with_debug),
        "successful_samples": successful_samples,
        "failed_samples": failed_samples,
        "referenced_debug_paths": referenced_paths,
        "existing_debug_files": existing_paths,
        "readable_debug_files": readable_paths,
        "first_debug_timestamp": round(min(timestamps), 4) if timestamps else None,
        "last_debug_timestamp": round(max(timestamps), 4) if timestamps else None,
        "report_debug_artifacts": debug_artifacts,
        "failures": failures,
        "missing_paths_sample": missing_paths[:20],
        "unreadable_paths_sample": unreadable_paths[:20],
        "samples_without_debug_sample": samples_without_debug[:20],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
