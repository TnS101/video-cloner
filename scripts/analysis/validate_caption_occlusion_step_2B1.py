#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List


EXPECTED_VERSION = "caption_occlusion_v1_9_classification_promotion_cue_reconciliation"


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_nested(data: Dict[str, Any], path: List[str], default: Any = None) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Video Cloner caption occlusion Step 2B.1.")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    report = load_json(args.report)
    events = report.get("occlusion_events") if isinstance(report.get("occlusion_events"), list) else []
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    audit = report.get("classification_audit") if isinstance(report.get("classification_audit"), dict) else {}
    normalization = report.get("normalization") if isinstance(report.get("normalization"), dict) else {}
    cue_reconciliation = normalization.get("cue_reconciliation") if isinstance(normalization.get("cue_reconciliation"), dict) else {}

    failures: List[str] = []

    if report.get("analysis_version") != EXPECTED_VERSION:
        failures.append(f"analysis_version={report.get('analysis_version')!r}")
    if not report.get("success") or not report.get("ok"):
        failures.append("report_not_successful")
    if len(events) != 95:
        failures.append(f"event_count={len(events)}")
    if summary.get("events_analyzed_count") != 95:
        failures.append(f"events_analyzed_count={summary.get('events_analyzed_count')}")
    if summary.get("mask_assets_incomplete_count") != 0:
        failures.append(f"mask_assets_incomplete_count={summary.get('mask_assets_incomplete_count')}")
    if not summary.get("ready_for_merge_analysis"):
        failures.append("ready_for_merge_analysis_false")
    if not summary.get("ready_for_editor_compilers"):
        failures.append("ready_for_editor_compilers_false")
    if int(summary.get("editor_ready_matte_count") or 0) < 1:
        failures.append(f"editor_ready_matte_count={summary.get('editor_ready_matte_count')}")
    if int(summary.get("needs_foreground_mask_count") or 0) < 1:
        failures.append(f"needs_foreground_mask_count={summary.get('needs_foreground_mask_count')}")
    if int(summary.get("non_caption_graphic_count") or 0) < 10:
        failures.append(f"non_caption_graphic_count={summary.get('non_caption_graphic_count')}")
    if int(summary.get("aggregate_caption_window_count") or 0) < 5:
        failures.append(f"aggregate_caption_window_count={summary.get('aggregate_caption_window_count')}")
    if int(summary.get("unresolved_caption_event_count") or 0) != 0:
        failures.append(f"unresolved_caption_event_count={summary.get('unresolved_caption_event_count')}")

    if not audit.get("complete"):
        failures.append("classification_audit_incomplete")
    if int(audit.get("event_sheet_count") or 0) != 95:
        failures.append(f"event_sheet_count={audit.get('event_sheet_count')}")
    if int(audit.get("logical_conflict_count") or 0) != 0:
        failures.append(f"logical_conflict_count={audit.get('logical_conflict_count')}")
    if int(audit.get("review_required_count") or 0) != 0:
        failures.append(f"review_required_count={audit.get('review_required_count')}")
    if int(audit.get("invalid_cue_id_count") or 0) != 0:
        failures.append(f"invalid_cue_id_count={audit.get('invalid_cue_id_count')}")
    if int(audit.get("editor_ready_matte_count") or 0) < 1:
        failures.append(f"audit_editor_ready_matte_count={audit.get('editor_ready_matte_count')}")

    if int(cue_reconciliation.get("aggregate_caption_window_count") or 0) < 5:
        failures.append(f"cue_reconciliation.aggregate={cue_reconciliation.get('aggregate_caption_window_count')}")
    if int(cue_reconciliation.get("non_caption_graphic_count") or 0) < 10:
        failures.append(f"cue_reconciliation.graphics={cue_reconciliation.get('non_caption_graphic_count')}")
    if int(cue_reconciliation.get("unresolved_count") or 0) != 0:
        failures.append(f"cue_reconciliation.unresolved={cue_reconciliation.get('unresolved_count')}")

    by_cue = {
        str(event.get("cue_id") or ""): event
        for event in events
        if isinstance(event, dict)
    }

    come = by_cue.get("sub_0052")
    if not come:
        failures.append("sub_0052_missing")
    else:
        occ = come.get("occlusion") or {}
        asset = come.get("mask_asset") or {}
        if occ.get("layer_order") != "foreground_over_text":
            failures.append(f"sub_0052.layer_order={occ.get('layer_order')}")
        if not occ.get("needs_foreground_mask"):
            failures.append("sub_0052.mask_not_requested")
        if occ.get("review_required"):
            failures.append("sub_0052.review_required")
        if not occ.get("ready_for_editor_compositing"):
            failures.append("sub_0052.not_editor_ready")
        if not asset.get("complete"):
            failures.append("sub_0052.mask_asset_incomplete")

    the_event = by_cue.get("sub_0079")
    if not the_event:
        failures.append("sub_0079_missing")
    else:
        occ = the_event.get("occlusion") or {}
        if occ.get("needs_foreground_mask"):
            failures.append("sub_0079_false_positive_mask")
        if occ.get("review_required"):
            failures.append("sub_0079_review_required")

    conflicts = []
    editor_ready = []
    editor_excluded = []
    for event in events:
        if not isinstance(event, dict):
            continue
        occ = event.get("occlusion") or {}
        excluded = bool(event.get("exclude_from_caption_occlusion_editor"))
        if excluded:
            editor_excluded.append(event.get("index"))
            if occ.get("needs_foreground_mask") or occ.get("review_required"):
                conflicts.append({
                    "index": event.get("index"),
                    "reason": "excluded_event_has_mask_or_review",
                })
        if occ.get("layer_order") == "text_over_foreground" and occ.get("needs_foreground_mask"):
            conflicts.append({
                "index": event.get("index"),
                "reason": "front_event_has_mask",
            })
        if occ.get("ready_for_editor_compositing"):
            editor_ready.append(event.get("index"))

    if conflicts:
        failures.append(f"runtime_conflicts={len(conflicts)}")

    result = {
        "ok": not failures,
        "analysis_version": report.get("analysis_version"),
        "events": len(events),
        "summary": {
            "layer_counts": audit.get("layer_order_counts"),
            "label_counts": audit.get("label_counts"),
            "review_required_count": audit.get("review_required_count"),
            "editor_ready_matte_count": audit.get("editor_ready_matte_count"),
            "excluded_event_count": audit.get("excluded_event_count"),
            "non_caption_graphic_count": audit.get("non_caption_graphic_count"),
            "aggregate_caption_window_count": audit.get("aggregate_caption_window_count"),
            "mask_assets_complete_count": summary.get("mask_assets_complete_count"),
            "mask_frames_written": summary.get("mask_frames_written"),
            "ready_for_merge_analysis": summary.get("ready_for_merge_analysis"),
            "ready_for_editor_compilers": summary.get("ready_for_editor_compilers"),
        },
        "cue_reconciliation": cue_reconciliation,
        "editor_ready_event_indexes": editor_ready,
        "editor_excluded_event_count": len(editor_excluded),
        "conflicts": conflicts,
        "failures": failures,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
