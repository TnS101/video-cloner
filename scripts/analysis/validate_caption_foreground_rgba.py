#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import cv2
import numpy as np


EXPECTED_VERSION = "caption_foreground_rgba_v1_2_local_caption_occlusion_patch"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Step 2D full-resolution RGBA foreground assets.")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--output-report", default="")
    args = parser.parse_args()

    contract_path = Path(args.contract)
    payload = load_json(contract_path)
    failures: List[str] = []

    if payload.get("builder_version") != EXPECTED_VERSION:
        failures.append(
            f"builder_version_mismatch:{payload.get('builder_version')!r}"
        )
    if not payload.get("success") or not payload.get("ok"):
        failures.append("asset_contract_not_successful")

    source_info = payload.get("source_video_info") or {}
    expected_width = int(source_info.get("width") or 0)
    expected_height = int(source_info.get("height") or 0)

    spans = payload.get("asset_spans") or []
    if not spans:
        failures.append("asset_spans_empty")

    rgba_files = 0
    readable_rgba_files = 0
    transparent_files = 0
    nonempty_foreground_files = 0
    bad_channel_files: List[str] = []
    bad_dimension_files: List[str] = []
    missing_files: List[str] = []
    unreadable_files: List[str] = []
    frame_number_errors: List[str] = []

    for span in spans:
        span_id = str(span.get("span_id") or "")
        if not span.get("complete"):
            failures.append(f"{span_id}:span_incomplete")
        if span.get("asset_scope") != "local_foreground_patch_intersecting_caption_region":
            failures.append(f"{span_id}:wrong_asset_scope")
        asset = span.get("rgba_asset") or {}
        manifest_path = Path(str(asset.get("manifest") or ""))
        if not manifest_path.is_file():
            failures.append(f"{span_id}:manifest_missing")
            continue
        manifest = load_json(manifest_path)
        if not manifest.get("complete"):
            failures.append(f"{span_id}:manifest_incomplete")
        if manifest.get("alpha_mode") != "straight_unassociated":
            failures.append(f"{span_id}:wrong_alpha_mode")
        if manifest.get("pixel_format") != "RGBA8":
            failures.append(f"{span_id}:wrong_pixel_format")

        start = int(span.get("timeline_frame_start") or 0)
        end = int(span.get("timeline_frame_end_exclusive") or 0)
        expected = end - start
        if expected != int(span.get("duration_frames") or -1):
            failures.append(f"{span_id}:duration_mismatch")

        event_dir = Path(str(asset.get("event_dir") or ""))
        caption_region = span.get("caption_region") or {}
        region_runtime = caption_region.get("runtime") or {}
        region_bbox = region_runtime.get("expanded_pixel_bbox")
        if (
            not isinstance(region_bbox, list)
            or len(region_bbox) != 4
        ):
            failures.append(f"{span_id}:caption_region_missing")
            region_bbox = None

        for frame_index in range(start, end):
            rgba_path = event_dir / f"rgba_{frame_index:06d}.png"
            rgba_files += 1
            if not rgba_path.is_file():
                missing_files.append(str(rgba_path))
                continue
            image = cv2.imread(str(rgba_path), cv2.IMREAD_UNCHANGED)
            if image is None:
                unreadable_files.append(str(rgba_path))
                continue
            readable_rgba_files += 1
            if image.ndim != 3 or image.shape[2] != 4:
                bad_channel_files.append(str(rgba_path))
                continue
            if image.shape[1] != expected_width or image.shape[0] != expected_height:
                bad_dimension_files.append(str(rgba_path))
            alpha = image[:, :, 3]
            if int(alpha.min()) < 255:
                transparent_files += 1
            if int(alpha.max()) > 0:
                nonempty_foreground_files += 1

            if region_bbox is not None:
                x1, y1, x2, y2 = [int(v) for v in region_bbox]
                outside = alpha.copy()
                outside[max(0, y1):max(0, y2), max(0, x1):max(0, x2)] = 0
                if int(np.count_nonzero(outside)) != 0:
                    failures.append(
                        f"{span_id}:alpha_exists_outside_caption_region:{frame_index}"
                    )

        if int(asset.get("frame_count_written") or -1) != expected:
            frame_number_errors.append(f"{span_id}:frame_count_written")
        if int(asset.get("frame_count_expected") or -1) != expected:
            frame_number_errors.append(f"{span_id}:frame_count_expected")

    if missing_files:
        failures.append(f"missing_rgba_files:{len(missing_files)}")
    if unreadable_files:
        failures.append(f"unreadable_rgba_files:{len(unreadable_files)}")
    if bad_channel_files:
        failures.append(f"bad_channel_files:{len(bad_channel_files)}")
    if bad_dimension_files:
        failures.append(f"bad_dimension_files:{len(bad_dimension_files)}")
    if frame_number_errors:
        failures.append(f"frame_number_errors:{len(frame_number_errors)}")
    if transparent_files != rgba_files:
        failures.append(
            f"not_all_frames_have_transparency:{transparent_files}/{rgba_files}"
        )
    if nonempty_foreground_files != rgba_files:
        failures.append(
            f"not_all_frames_have_foreground:{nonempty_foreground_files}/{rgba_files}"
        )

    timebase = payload.get("timebase") or {}
    contract_fps = float(timebase.get("contract_fps") or 0.0)
    source_fps = float(timebase.get("source_video_fps") or 0.0)
    mappings = timebase.get("frame_mappings") or []
    if contract_fps <= 0 or source_fps <= 0:
        failures.append("invalid_timebase_fps")
    if len(mappings) != rgba_files:
        failures.append(f"frame_mapping_count_mismatch:{len(mappings)}/{rgba_files}")
    max_mapping_error = max(
        (abs(float(m.get("timing_error_seconds") or 0.0)) for m in mappings),
        default=0.0,
    )
    allowed_error = (0.5 / source_fps) + 1e-6 if source_fps > 0 else 0.0
    if max_mapping_error > allowed_error:
        failures.append(
            f"timebase_mapping_error_too_large:{max_mapping_error:.9f}>{allowed_error:.9f}"
        )

    summary = payload.get("summary") or {}
    for key in ("ready_for_merge_analysis", "ready_for_editor_compilers", "ready_for_v4_import"):
        if not summary.get(key):
            failures.append(f"summary_{key}_false")

    result = {
        "ok": not failures,
        "builder_version": payload.get("builder_version"),
        "asset_span_count": len(spans),
        "source_resolution": [expected_width, expected_height],
        "contract_fps": contract_fps,
        "source_video_fps": source_fps,
        "timebase_remap_applied": bool(timebase.get("remap_applied")),
        "frame_mapping_count": len(mappings),
        "max_abs_timing_error_seconds": max_mapping_error,
        "rgba_files_expected": rgba_files,
        "rgba_files_readable": readable_rgba_files,
        "transparent_rgba_files": transparent_files,
        "nonempty_foreground_rgba_files": nonempty_foreground_files,
        "failures": failures,
        "missing_files_sample": missing_files[:20],
        "unreadable_files_sample": unreadable_files[:20],
        "bad_channel_files_sample": bad_channel_files[:20],
        "bad_dimension_files_sample": bad_dimension_files[:20],
        "frame_number_errors": frame_number_errors[:20],
    }

    if args.output_report:
        report_path = Path(args.output_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("w", encoding="utf-8", newline="\n") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            f.write("\n")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
