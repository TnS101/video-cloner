#!/usr/bin/env python3
"""
Video Cloner — Major Step 3C input bridge v1.1

Normalizes the successful Step 3B.2 plan/report into the exact structure
expected by caption_animation_step_3C.py.

Fixes:
- Step 3B.2 start/end -> Step 3C start_frame/end_frame.
- Mixed cue formats: 8, sub_008, sub_0008 are matched numerically.
- Preserves the actual cue spelling used by each VC_TEXTPLUS V3 item.
- Produces compact normalized inputs and detailed extraction diagnostics.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


VERSION = "prepare_caption_animation_step_3C_inputs_v1_1"
V3_NAME_RE = re.compile(
    r"^VC_TEXTPLUS_(?P<index>\d+)_(?P<cue>sub_\d+)$",
    re.IGNORECASE,
)
TRAILING_DIGITS_RE = re.compile(r"(\d+)$")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    temporary.replace(path)


def walk_nodes(root: Any) -> Iterable[Any]:
    stack = [root]

    while stack:
        node = stack.pop()
        yield node

        if isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def as_float(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None

    return result if math.isfinite(result) else None


def as_int(value: Any) -> Optional[int]:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def first_int(
    node: Dict[str, Any],
    keys: Sequence[str],
) -> Optional[int]:
    for key in keys:
        result = as_int(node.get(key))

        if result is not None:
            return result

    return None


def cue_number(value: Any) -> Optional[int]:
    text = str(value or "").strip()

    if not text:
        return None

    match = TRAILING_DIGITS_RE.search(text)

    if not match:
        return None

    try:
        return int(match.group(1))
    except ValueError:
        return None


def cue_from_v3_name(name: str) -> Optional[str]:
    match = V3_NAME_RE.match(str(name or "").strip())

    if match:
        return match.group("cue")

    fallback = re.search(
        r"(sub_\d+)$",
        str(name or "").strip(),
        re.IGNORECASE,
    )

    return fallback.group(1) if fallback else None


def extract_size(node: Dict[str, Any]) -> Optional[float]:
    for key in (
        "size_after",
        "target_size",
        "calibrated_size",
        "resolved_size",
        "final_size",
        "textplus_size",
    ):
        result = as_float(node.get(key))

        if result is not None and result > 0:
            return result

    after = node.get("after")

    if isinstance(after, dict):
        for key in ("Size", "size", "textplus_size"):
            result = as_float(after.get(key))

            if result is not None and result > 0:
                return result

    size_record = node.get("Size")

    if isinstance(size_record, dict):
        result = as_float(size_record.get("value"))

        if result is not None and result > 0:
            return result

    return None


def collect_v3_rows(
    size_plan: Any,
    size_report: Any,
) -> Tuple[List[Dict[str, Any]], Dict[int, Dict[str, Any]], Dict[str, Any]]:
    merged: Dict[int, Dict[str, Any]] = {}

    diagnostics: Dict[str, Any] = {
        "dict_nodes_seen": 0,
        "v3_named_nodes_seen": 0,
        "merged_numeric_cues": 0,
        "usable_v3_rows": 0,
        "rejected_rows": [],
    }

    for document_index, document in enumerate((size_plan, size_report)):
        for node in walk_nodes(document):
            if not isinstance(node, dict):
                continue

            diagnostics["dict_nodes_seen"] += 1

            name = str(
                node.get("name")
                or node.get("item_name")
                or node.get("clip_name")
                or ""
            ).strip()

            cue_id = cue_from_v3_name(name)

            # Only actual VC_TEXTPLUS rows are valid V3 candidates.
            if not cue_id:
                continue

            diagnostics["v3_named_nodes_seen"] += 1

            numeric_cue = cue_number(cue_id)

            if numeric_cue is None:
                continue

            target = merged.setdefault(
                numeric_cue,
                {
                    "numeric_cue": numeric_cue,
                    "source_documents": [],
                    "source_field_sets": [],
                },
            )

            if document_index not in target["source_documents"]:
                target["source_documents"].append(document_index)

            field_set = sorted(str(key) for key in node.keys())

            if field_set not in target["source_field_sets"]:
                target["source_field_sets"].append(field_set)

            target["name"] = name
            target["cue_id"] = cue_id

            for key in (
                "cue_index",
                "style_profile_id",
                "timeline_seconds",
                "rendered_text",
                "text",
                "family",
                "face",
            ):
                value = node.get(key)

                if value is not None and value != "":
                    target[key] = value

            start = first_int(
                node,
                (
                    "start_frame",
                    "timeline_frame",
                    "start",
                    "record_frame",
                    "record_start",
                ),
            )

            end = first_int(
                node,
                (
                    "end_frame",
                    "end",
                    "record_end",
                ),
            )

            duration = first_int(
                node,
                (
                    "duration_frames",
                    "frame_duration",
                ),
            )

            size = extract_size(node)

            if start is not None:
                target["start_frame"] = start

            if end is not None:
                target["end_frame"] = end

            if duration is not None:
                target["duration_frames"] = duration

            if size is not None:
                target["target_size"] = size

    diagnostics["merged_numeric_cues"] = len(merged)

    normalized_rows: List[Dict[str, Any]] = []
    by_number: Dict[int, Dict[str, Any]] = {}

    for numeric_cue in sorted(merged):
        row = merged[numeric_cue]

        start = as_int(row.get("start_frame"))
        end = as_int(row.get("end_frame"))
        duration = as_int(row.get("duration_frames"))
        size = as_float(row.get("target_size"))

        if duration is None and start is not None and end is not None:
            duration = max(0, end - start)

        if end is None and start is not None and duration is not None:
            end = start + duration

        if start is None and end is not None and duration is not None:
            start = end - duration

        missing: List[str] = []

        if not row.get("name"):
            missing.append("name")

        if not row.get("cue_id"):
            missing.append("cue_id")

        if start is None:
            missing.append("start_frame")

        if end is None:
            missing.append("end_frame")

        if duration is None or duration <= 0:
            missing.append("duration_frames")

        if size is None or size <= 0:
            missing.append("target_size")

        if missing:
            diagnostics["rejected_rows"].append(
                {
                    "numeric_cue": numeric_cue,
                    "name": row.get("name"),
                    "cue_id": row.get("cue_id"),
                    "missing": missing,
                    "start_frame": start,
                    "end_frame": end,
                    "duration_frames": duration,
                    "target_size": size,
                    "source_field_sets": row.get("source_field_sets"),
                }
            )
            continue

        normalized = {
            "name": row["name"],
            "cue_id": row["cue_id"],
            "cue_index": row.get("cue_index", numeric_cue),
            "start_frame": start,
            "end_frame": end,
            "duration_frames": duration,
            "timeline_frame": start,
            "timeline_seconds": row.get("timeline_seconds"),
            "target_size": size,
            "size_after": size,
            "rendered_text": row.get("rendered_text") or row.get("text"),
            "text": row.get("text") or row.get("rendered_text"),
            "style_profile_id": row.get("style_profile_id"),
            "family": row.get("family"),
            "face": row.get("face"),
        }

        normalized_rows.append(normalized)
        by_number[numeric_cue] = normalized

    diagnostics["usable_v3_rows"] = len(normalized_rows)

    return normalized_rows, by_number, diagnostics


def collect_animation_events(
    analysis: Any,
    v3_by_number: Dict[int, Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    for node in walk_nodes(analysis):
        if not isinstance(node, dict):
            continue

        animation = node.get("animation")
        numeric_cue = cue_number(node.get("cue_id"))

        if numeric_cue is None or not isinstance(animation, dict):
            continue

        if not bool(animation.get("detected")):
            continue

        animation_type = str(
            animation.get("type")
            or animation.get("style")
            or ""
        ).strip().lower()

        if not animation_type:
            continue

        candidates.append(node)

    deduplicated: Dict[str, Dict[str, Any]] = {}

    for event in candidates:
        animation = event.get("animation") or {}

        key = str(event.get("event_id") or "").strip()

        if not key:
            key = "|".join(
                [
                    str(cue_number(event.get("cue_id"))),
                    str(
                        animation.get("type")
                        or animation.get("style")
                        or ""
                    ),
                    str(event.get("start")),
                    str(event.get("end")),
                ]
            )

        previous = deduplicated.get(key)

        current_quality = (
            as_float(animation.get("confidence")) or 0.0,
            len(animation.get("keyframes") or []),
            as_int(animation.get("samples")) or 0,
        )

        if previous is None:
            deduplicated[key] = event
            continue

        previous_animation = previous.get("animation") or {}

        previous_quality = (
            as_float(previous_animation.get("confidence")) or 0.0,
            len(previous_animation.get("keyframes") or []),
            as_int(previous_animation.get("samples")) or 0,
        )

        if current_quality > previous_quality:
            deduplicated[key] = event

    normalized_events: List[Dict[str, Any]] = []
    unmatched_events: List[Dict[str, Any]] = []
    type_counts: Dict[str, int] = {}

    for event in deduplicated.values():
        numeric_cue = cue_number(event.get("cue_id"))
        target = v3_by_number.get(numeric_cue or -1)
        animation = event.get("animation") or {}

        animation_type = str(
            animation.get("type")
            or animation.get("style")
            or "unknown"
        ).strip().lower()

        type_counts[animation_type] = (
            type_counts.get(animation_type, 0) + 1
        )

        if target is None:
            unmatched_events.append(
                {
                    "event_id": event.get("event_id"),
                    "source_cue_id": event.get("cue_id"),
                    "numeric_cue": numeric_cue,
                    "animation_type": animation_type,
                }
            )
            continue

        normalized = copy.deepcopy(event)

        normalized["source_cue_id_before_bridge"] = event.get("cue_id")
        normalized["cue_id"] = target["cue_id"]
        normalized["target_v3_name"] = target["name"]

        normalized_events.append(normalized)

    normalized_events.sort(
        key=lambda row: (
            cue_number(row.get("cue_id")) or 10**9,
            str(row.get("event_id") or ""),
        )
    )

    diagnostics = {
        "raw_detected_candidates": len(candidates),
        "deduplicated_event_count": len(deduplicated),
        "normalized_event_count": len(normalized_events),
        "unmatched_event_count": len(unmatched_events),
        "animation_type_counts": type_counts,
        "unmatched_events": unmatched_events,
    }

    return normalized_events, diagnostics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize Step 3B.2 inputs for Step 3C."
    )

    parser.add_argument("--analysis", required=True)
    parser.add_argument("--font-size-plan", required=True)
    parser.add_argument("--font-size-report", required=True)

    parser.add_argument("--output-analysis", required=True)
    parser.add_argument("--output-font-size-plan", required=True)
    parser.add_argument("--output-font-size-report", required=True)
    parser.add_argument("--output-validation", required=True)

    parser.add_argument("--expected-v3-count", type=int, default=116)
    parser.add_argument(
        "--expected-animation-count",
        type=int,
        default=11,
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    analysis_path = Path(args.analysis)
    size_plan_path = Path(args.font_size_plan)
    size_report_path = Path(args.font_size_report)

    analysis = load_json(analysis_path)
    size_plan = load_json(size_plan_path)
    size_report = load_json(size_report_path)

    v3_rows, v3_by_number, v3_diagnostics = collect_v3_rows(
        size_plan,
        size_report,
    )

    animation_events, animation_diagnostics = collect_animation_events(
        analysis,
        v3_by_number,
    )

    checks = {
        "expected_v3_count": (
            len(v3_rows) == args.expected_v3_count
        ),
        "expected_animation_count": (
            args.expected_animation_count <= 0
            or len(animation_events)
            == args.expected_animation_count
        ),
        "all_animation_events_linked": (
            animation_diagnostics["unmatched_event_count"] == 0
        ),
        "v3_names_unique": (
            len({row["name"] for row in v3_rows})
            == len(v3_rows)
        ),
        "v3_cue_ids_unique": (
            len({row["cue_id"] for row in v3_rows})
            == len(v3_rows)
        ),
    }

    normalized_analysis = {
        "success": all(checks.values()),
        "schema": "video_cloner_caption_animation_bridge",
        "schema_version": "1.1",
        "version": VERSION,
        "caption_style_events": animation_events,
        "summary": animation_diagnostics,
    }

    normalized_size_payload = {
        "ok": all(checks.values()),
        "schema": "video_cloner_step_3C_normalized_v3_map",
        "schema_version": "1.1",
        "version": VERSION,
        "items": v3_rows,
        "summary": {
            "items": len(v3_rows),
        },
    }

    validation = {
        "ok": all(checks.values()),
        "step": "Major Step 3C input bridge",
        "version": VERSION,
        "inputs": {
            "analysis": str(analysis_path),
            "font_size_plan": str(size_plan_path),
            "font_size_report": str(size_report_path),
        },
        "outputs": {
            "analysis": args.output_analysis,
            "font_size_plan": args.output_font_size_plan,
            "font_size_report": args.output_font_size_report,
        },
        "summary": {
            "v3_item_count": len(v3_rows),
            "animation_event_count": len(animation_events),
            "animation_type_counts": (
                animation_diagnostics["animation_type_counts"]
            ),
        },
        "v3_extraction": v3_diagnostics,
        "animation_extraction": animation_diagnostics,
        "checks": checks,
        "failures": [
            key for key, passed in checks.items() if not passed
        ],
    }

    write_json(
        Path(args.output_analysis),
        normalized_analysis,
    )
    write_json(
        Path(args.output_font_size_plan),
        normalized_size_payload,
    )
    write_json(
        Path(args.output_font_size_report),
        normalized_size_payload,
    )
    write_json(
        Path(args.output_validation),
        validation,
    )

    print(json.dumps(validation, ensure_ascii=False, indent=2))

    if validation["ok"]:
        print()
        print(
            "PASS: Step 3C bridge normalized "
            f"{len(v3_rows)} V3 items and "
            f"{len(animation_events)} animation events."
        )
        return 0

    print()
    print("ERROR: Step 3C input bridge validation failed.")
    print(
        "Read v3_extraction.rejected_rows and "
        "animation_extraction.unmatched_events."
    )
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "version": VERSION,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(1)