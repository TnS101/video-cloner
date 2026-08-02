#!/usr/bin/env python3
"""Independent validator for Video Cloner Step 2C matte-span contracts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set

try:
    import cv2  # type: ignore
except Exception:
    cv2 = None


SCHEMA = "video_cloner_caption_matte_contract"
BUILDER_VERSION = "caption_matte_contract_v1_0_interval_merge_dedup"
CUE_RE = re.compile(r"^sub_\d{4}$")


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("Contract root must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate normalized caption matte spans.")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--require-builder-version", default=BUILDER_VERSION)
    parser.add_argument("--allow-zero-spans", action="store_true")
    args = parser.parse_args()

    contract_path = Path(args.contract).resolve()
    contract = load_json(contract_path)
    failures: List[str] = []

    if contract.get("schema") != SCHEMA:
        failures.append(f"schema_mismatch:{contract.get('schema')!r}")
    if args.require_builder_version and contract.get("builder_version") != args.require_builder_version:
        failures.append(f"builder_version_mismatch:{contract.get('builder_version')!r}")
    if not contract.get("success") or not contract.get("ok"):
        failures.append("contract_not_ok")

    summary = contract.get("summary") if isinstance(contract.get("summary"), dict) else {}
    spans = contract.get("matte_spans") if isinstance(contract.get("matte_spans"), list) else []
    if not spans and not args.allow_zero_spans:
        failures.append("zero_matte_spans")
    if int(summary.get("normalized_matte_span_count") or -1) != len(spans):
        failures.append("summary_span_count_mismatch")
    if int(summary.get("incomplete_span_count") or 0) != 0:
        failures.append("incomplete_spans_reported")
    if int(summary.get("mask_hash_conflict_count") or 0) != 0:
        failures.append("mask_hash_conflicts_reported")
    if int(summary.get("missing_frame_count") or 0) != 0:
        failures.append("missing_frames_reported")
    if int(summary.get("unreadable_frame_count") or 0) != 0:
        failures.append("unreadable_frames_reported")
    if int(summary.get("interval_conflict_count") or 0) != 0:
        failures.append("interval_conflicts_reported")
    if not summary.get("ready_for_matte_asset_build"):
        failures.append("ready_for_matte_asset_build_false")

    seen_source_frames: Set[int] = set()
    seen_timeline_frames: Set[int] = set()
    seen_paths: Set[str] = set()
    previous_end = None
    actual_frame_count = 0
    readable_frame_count = 0

    for span in spans:
        span_id = str(span.get("span_id") or "")
        if not span.get("complete"):
            failures.append(f"{span_id}:incomplete")
        start = int(span.get("source_frame_start") or 0)
        end = int(span.get("source_frame_end_exclusive") or 0)
        timeline_start = int(span.get("timeline_frame_start") or 0)
        timeline_end = int(span.get("timeline_frame_end_exclusive") or 0)
        duration = int(span.get("duration_frames") or 0)
        if end <= start or duration != end - start:
            failures.append(f"{span_id}:invalid_source_interval")
        if timeline_end - timeline_start != duration:
            failures.append(f"{span_id}:invalid_timeline_interval")
        if previous_end is not None and start <= previous_end:
            failures.append(f"{span_id}:overlap_or_unmerged_adjacency")
        previous_end = end

        cue_ids = span.get("affected_cue_ids") if isinstance(span.get("affected_cue_ids"), list) else []
        if not cue_ids or any(not CUE_RE.fullmatch(str(cue)) for cue in cue_ids):
            failures.append(f"{span_id}:invalid_affected_cue_ids")

        asset = span.get("mask_asset") if isinstance(span.get("mask_asset"), dict) else {}
        if not asset.get("complete"):
            failures.append(f"{span_id}:mask_asset_incomplete")
        if int(asset.get("frame_count_expected") or -1) != duration:
            failures.append(f"{span_id}:asset_expected_count_mismatch")
        if int(asset.get("frame_count_written") or -1) != duration:
            failures.append(f"{span_id}:asset_written_count_mismatch")
        width = int(asset.get("width") or 0)
        height = int(asset.get("height") or 0)
        pattern = str(asset.get("mask_pattern") or "")
        if width <= 0 or height <= 0 or not pattern:
            failures.append(f"{span_id}:invalid_asset_metadata")
            continue

        for offset, frame in enumerate(range(start, end)):
            try:
                path = Path(pattern % frame)
            except Exception:
                failures.append(f"{span_id}:invalid_mask_pattern")
                break
            timeline_frame = timeline_start + offset
            if frame in seen_source_frames:
                failures.append(f"duplicate_source_frame:{frame}")
            if timeline_frame in seen_timeline_frames:
                failures.append(f"duplicate_timeline_frame:{timeline_frame}")
            if str(path) in seen_paths:
                failures.append(f"duplicate_canonical_path:{path}")
            seen_source_frames.add(frame)
            seen_timeline_frames.add(timeline_frame)
            seen_paths.add(str(path))
            actual_frame_count += 1
            if not path.is_file():
                failures.append(f"missing_file:{path}")
                continue
            if cv2 is None:
                failures.append("opencv_not_available")
                continue
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is None or image.size == 0:
                failures.append(f"unreadable_file:{path}")
                continue
            actual_height, actual_width = image.shape[:2]
            if actual_width != width or actual_height != height:
                failures.append(f"wrong_dimensions:{path}:{actual_width}x{actual_height}")
                continue
            readable_frame_count += 1

    if int(summary.get("unique_source_frame_count") or -1) != len(seen_source_frames):
        failures.append("summary_unique_source_frame_count_mismatch")
    if int(summary.get("canonical_frames_written") or -1) != actual_frame_count:
        failures.append("summary_canonical_frames_written_mismatch")

    result = {
        "ok": not failures,
        "contract": str(contract_path),
        "builder_version": contract.get("builder_version"),
        "span_count": len(spans),
        "source_frame_count": len(seen_source_frames),
        "timeline_frame_count": len(seen_timeline_frames),
        "canonical_file_count": actual_frame_count,
        "readable_file_count": readable_frame_count,
        "summary": summary,
        "failures": failures,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
