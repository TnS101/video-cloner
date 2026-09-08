#!/usr/bin/env python3
"""Validate artifacts from the temporal baked-caption removal window probe."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

TASK_ID = "DZSQH7AUHJT_STEP_3D_CAPTION_REMOVAL_TEMPORAL_WINDOW_PROBE_V1"
SCHEMA = "video_cloner_baked_caption_removal_temporal_window_probe"


def validate(output_dir: Path) -> Dict[str, Any]:
    report_path = output_dir / "report.json"
    if not report_path.is_file():
        raise RuntimeError(f"report_missing:{report_path}")
    with report_path.open("r", encoding="utf-8-sig") as handle:
        report = json.load(handle)
    errors = []
    if report.get("task_id") != TASK_ID:
        errors.append("task_id_mismatch")
    if report.get("schema") != SCHEMA:
        errors.append("schema_mismatch")
    if report.get("ok") is not True:
        errors.append("report_not_ok")
    if report.get("context_window") != [416, 468]:
        errors.append("context_window_mismatch")
    if report.get("output_window") != [420, 463]:
        errors.append("output_window_mismatch")
    if report.get("clean_window") != [428, 452]:
        errors.append("clean_window_mismatch")
    if int(report.get("output_frame_count", -1)) != 43:
        errors.append("output_frame_count_mismatch")
    if int(report.get("target_frame_count", -1)) != 24:
        errors.append("target_frame_count_mismatch")
    if float(report.get("max_outside_mask_mean_abs_diff", 999.0)) != 0.0:
        errors.append("outside_mask_changed")
    if float(report.get("median_donor_coverage_ratio", -1.0)) < 0.25:
        errors.append("donor_coverage_insufficient")
    if float(report.get("max_unresolved_ratio", 999.0)) > 0.90:
        errors.append("unresolved_ratio_excessive")
    if float(report.get("median_masked_local_contrast_ratio", 999.0)) >= 1.0:
        errors.append("contrast_not_reduced")
    if float(report.get("minimum_target_mask_area_ratio", -1.0)) < 0.01:
        errors.append("target_mask_area_too_small")
    if float(report.get("maximum_target_mask_area_ratio", 999.0)) > 0.10:
        errors.append("target_mask_area_too_large")
    if float(report.get("median_inside_mask_mean_abs_diff", -1.0)) < 1.0:
        errors.append("target_region_not_modified")
    if report.get("palette_residual_metric_role") != "diagnostic_only":
        errors.append("palette_metric_role_mismatch")
    backend_counts = report.get("segmentation_backend_counts") or {}
    if backend_counts != {"paddle_humanseg": 52}:
        errors.append("paddle_backend_not_exclusive")
    for name, passed in (report.get("checks") or {}).items():
        if passed is not True:
            errors.append(f"check_failed:{name}")

    artifacts = report.get("artifacts") or {}
    file_keys = (
        "cleaned_video",
        "before_after_contact_sheet",
        "mask_contact_sheet",
        "donor_coverage_contact_sheet",
    )
    for key in file_keys:
        raw = artifacts.get(key)
        path = Path(str(raw or ""))
        if not raw or not path.is_file() or path.stat().st_size <= 0:
            errors.append(f"artifact_missing:{key}:{path}")
    directory_expectations = {
        "cleaned_frames": ("frame_*.png", 43),
        "caption_masks": ("mask_*.png", 43),
        "foreground_masks": ("foreground_*.png", 43),
        "donor_coverage": ("coverage_*.png", 43),
    }
    for key, (pattern, expected) in directory_expectations.items():
        path = Path(str(artifacts.get(key) or ""))
        if len(list(path.glob(pattern))) != expected:
            errors.append(f"artifact_count_mismatch:{key}")
    if errors:
        raise RuntimeError(";".join(errors))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir")
    args = parser.parse_args()
    try:
        report = validate(Path(args.output_dir).resolve())
    except Exception as exc:
        print(f"FAIL {TASK_ID}: {exc}", file=sys.stderr)
        return 1
    print(f"PASS {TASK_ID}")
    print(f"Frames: {report['output_frame_count']}")
    print(f"Median donor coverage: {report['median_donor_coverage_ratio']}")
    print(f"Max unresolved ratio: {report['max_unresolved_ratio']}")
    print(f"Review: {report['artifacts']['before_after_contact_sheet']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
