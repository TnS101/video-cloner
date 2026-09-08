#!/usr/bin/env python3
"""Validate terminal artifacts from the baked-caption removal window probe."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

TASK_ID = "DZSQH7AUHJT_STEP_3D_CAPTION_REMOVAL_WINDOW_PROBE_V1"
SCHEMA = "video_cloner_baked_caption_removal_window_probe"


def load_report(output_dir: Path) -> Dict[str, Any]:
    report_path = output_dir / "report.json"
    if not report_path.is_file():
        raise RuntimeError(f"report_missing:{report_path}")
    with report_path.open("r", encoding="utf-8-sig") as handle:
        report = json.load(handle)
    if not isinstance(report, dict):
        raise RuntimeError("report_root_not_object")
    return report


def validate(output_dir: Path) -> Dict[str, Any]:
    report = load_report(output_dir)
    errors = []
    if report.get("task_id") != TASK_ID:
        errors.append("task_id_mismatch")
    if report.get("schema") != SCHEMA:
        errors.append("schema_mismatch")
    if report.get("ok") is not True:
        errors.append("report_not_ok")
    if report.get("frame_window") != [420, 463]:
        errors.append("frame_window_mismatch")
    if report.get("clean_window") != [428, 452]:
        errors.append("clean_window_mismatch")
    if int(report.get("frame_count", -1)) != 43:
        errors.append("frame_count_mismatch")
    if int(report.get("target_frame_count", -1)) != 24:
        errors.append("target_frame_count_mismatch")
    if int(report.get("masked_target_frame_count", -1)) < int(report.get("minimum_masked_target_frame_count", 999999)):
        errors.append("masked_frame_coverage_insufficient")
    if float(report.get("max_outside_mask_mean_abs_diff", 999.0)) != 0.0:
        errors.append("outside_mask_changed")
    if float(report.get("max_protected_foreground_mean_abs_diff", 999.0)) != 0.0:
        errors.append("foreground_changed")
    if float(report.get("median_masked_local_contrast_ratio", 999.0)) >= 1.0:
        errors.append("contrast_not_reduced")
    backend_counts = report.get("segmentation_backend_counts") or {}
    if set(backend_counts) != {"paddle_humanseg"} or int(backend_counts.get("paddle_humanseg", 0)) != 43:
        errors.append("paddle_backend_not_exclusive")
    checks = report.get("checks") or {}
    for name, passed in checks.items():
        if passed is not True:
            errors.append(f"check_failed:{name}")
    artifacts = report.get("artifacts") or {}
    for key in ("cleaned_video", "before_after_contact_sheet", "mask_contact_sheet"):
        raw = artifacts.get(key)
        if not raw:
            errors.append(f"artifact_path_missing:{key}")
            continue
        path = Path(raw)
        if not path.is_file() or path.stat().st_size <= 0:
            errors.append(f"artifact_missing_or_empty:{key}:{path}")
    frames_dir = Path(str(artifacts.get("cleaned_frames") or ""))
    masks_dir = Path(str(artifacts.get("caption_masks") or ""))
    foreground_dir = Path(str(artifacts.get("foreground_masks") or ""))
    if len(list(frames_dir.glob("frame_*.png"))) != 43:
        errors.append("cleaned_frame_artifact_count_mismatch")
    if len(list(masks_dir.glob("mask_*.png"))) != 43:
        errors.append("caption_mask_artifact_count_mismatch")
    if len(list(foreground_dir.glob("foreground_*.png"))) != 43:
        errors.append("foreground_mask_artifact_count_mismatch")
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
    print(f"Frames: {report['frame_count']}")
    print(f"Masked target frames: {report['masked_target_frame_count']} / {report['target_frame_count']}")
    print(f"Median contrast ratio: {report['median_masked_local_contrast_ratio']}")
    print(f"Review: {report['artifacts']['before_after_contact_sheet']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
