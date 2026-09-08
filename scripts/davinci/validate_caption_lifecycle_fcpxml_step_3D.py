#!/usr/bin/env python3
"""Validate a Step 3D calibrated-lifecycle FCPXML compilation."""
from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

SCHEMA = "video_cloner_caption_lifecycle_fcpxml_validation"
SCHEMA_VERSION = 1
TITLE_INDEX_RE = re.compile(r"\b(?P<index>\d{4})\b")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fcpx_time_to_frames(value: str, fps: float) -> int:
    text = str(value or "").strip()
    if not text.endswith("s"):
        raise ValueError(f"unsupported FCPXML time: {value}")
    body = text[:-1]
    if "/" in body:
        numerator, denominator = body.split("/", 1)
        seconds = float(numerator) / float(denominator)
    else:
        seconds = float(body)
    return int(round(seconds * fps))


def normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_titles(fcpxml_path: Path, fps: float) -> list[dict[str, Any]]:
    root = ET.parse(fcpxml_path).getroot()
    rows: list[dict[str, Any]] = []
    for title in root.iter("title"):
        name = title.attrib.get("name", "")
        match = TITLE_INDEX_RE.search(name)
        if not match or not name.startswith("VC Caption"):
            continue
        text_node = title.find("./text/text-style")
        rows.append({
            "index": int(match.group("index")),
            "name": name,
            "lane": int(title.attrib.get("lane", "1")),
            "start_frame": fcpx_time_to_frames(title.attrib.get("offset", "0s"), fps),
            "duration_frames": fcpx_time_to_frames(title.attrib.get("duration", "0s"), fps),
            "text": normalized_text(text_node.text if text_node is not None else ""),
        })
    rows.sort(key=lambda row: row["index"])
    return rows


def validate(plan: dict[str, Any], report: dict[str, Any], titles: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    layers = plan.get("layers") if isinstance(plan.get("layers"), list) else []
    summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
    lifecycle = report.get("caption_lifecycle") if isinstance(report.get("caption_lifecycle"), dict) else {}

    if plan.get("ok") is not True:
        failures.append("plan_not_ok")
    if report.get("success") is not True:
        failures.append("compiler_report_not_success")
    if lifecycle.get("enabled") is not True:
        failures.append("lifecycle_not_enabled")
    if len(titles) != len(layers):
        failures.append(f"title_count:{len(titles)}:{len(layers)}")

    by_index = {int(layer.get("cue_index", 0)): layer for layer in layers if isinstance(layer, dict)}
    if len(by_index) != len(layers):
        failures.append("duplicate_or_invalid_layer_index")

    lane_intervals: dict[int, list[tuple[int, int, int]]] = {}
    mismatches: list[str] = []
    for title in titles:
        layer = by_index.get(title["index"])
        if not layer:
            mismatches.append(f"missing_layer:{title['index']}")
            continue
        window = layer.get("lifecycle_window")
        if not isinstance(window, list) or len(window) != 2:
            mismatches.append(f"bad_window:{title['index']}")
            continue
        expected_start = int(window[0])
        expected_end = int(window[1])
        actual_end = title["start_frame"] + title["duration_frames"]
        if title["start_frame"] != expected_start or actual_end != expected_end:
            mismatches.append(
                f"timing:{title['index']}:{title['start_frame']}-{actual_end}:{expected_start}-{expected_end}"
            )
        expected_text = normalized_text(layer.get("text"))
        if title["text"] != expected_text:
            mismatches.append(f"text:{title['index']}:{title['text']}:{expected_text}")
        lane_intervals.setdefault(title["lane"], []).append((title["start_frame"], actual_end, title["index"]))

    if mismatches:
        failures.append("title_contract:" + ",".join(mismatches[:20]))

    lane_overlap_failures: list[str] = []
    for lane, intervals in sorted(lane_intervals.items()):
        intervals.sort()
        for previous, current in zip(intervals, intervals[1:]):
            if current[0] < previous[1]:
                lane_overlap_failures.append(
                    f"lane_{lane}:{previous[2]}[{previous[0]},{previous[1]})/"
                    f"{current[2]}[{current[0]},{current[1]})"
                )
    if lane_overlap_failures:
        failures.append("same_lane_overlap:" + ",".join(lane_overlap_failures[:20]))

    expected_counts = {
        "visual_primary_count": int(summary.get("visual_primary_count", 0)),
        "transcript_fallback_count": int(summary.get("transcript_fallback_count", 0)),
        "animated_caption_count": int(summary.get("selected_animation_count", 0)),
        "animated_visual_lifecycle_count": int(summary.get("selected_animation_visual_primary_count", 0)),
    }
    for key, expected in expected_counts.items():
        if int(lifecycle.get(key, -1)) != expected:
            failures.append(f"count:{key}:{lifecycle.get(key)}:{expected}")

    lane_info = lifecycle.get("lane_allocation") if isinstance(lifecycle.get("lane_allocation"), dict) else {}
    actual_lanes = sorted(lane_intervals)
    if int(lane_info.get("lane_count", -1)) != len(actual_lanes):
        failures.append("lane_count")
    if actual_lanes and int(lane_info.get("max_lane", -1)) != max(actual_lanes):
        failures.append("max_lane")

    targets = {
        "sub_052": [430, 452],
        "sub_057": [454, 493],
        "sub_058": [456, 492],
        "sub_081": [628, 656],
    }
    layer_by_cue = {str(layer.get("cue_id")): layer for layer in layers if isinstance(layer, dict)}
    target_results = {}
    for cue_id, expected_window in targets.items():
        layer = layer_by_cue.get(cue_id) or {}
        matched = layer.get("lifecycle_window") == expected_window
        target_results[cue_id] = {
            "expected_window": expected_window,
            "actual_window": layer.get("lifecycle_window"),
            "matched": matched,
        }
        if not matched:
            failures.append(f"target_window:{cue_id}")

    return {
        "ok": not failures,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "caption_count": len(titles),
        "lane_count": len(actual_lanes),
        "lanes": actual_lanes,
        "same_lane_overlap_count": len(lane_overlap_failures),
        "visual_primary_count": lifecycle.get("visual_primary_count"),
        "transcript_fallback_count": lifecycle.get("transcript_fallback_count"),
        "animated_visual_lifecycle_count": lifecycle.get("animated_visual_lifecycle_count"),
        "target_results": target_results,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--fcpxml", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fps", type=float, default=24.0)
    args = parser.parse_args()

    plan = load_json(args.plan)
    report = load_json(args.report)
    titles = parse_titles(args.fcpxml, args.fps)
    result = validate(plan, report, titles)
    write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
