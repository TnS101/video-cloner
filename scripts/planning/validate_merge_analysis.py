#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List


VALIDATOR_VERSION = "validate_merge_analysis_step_2E_v1_1_deployment_safe"
EXPECTED_VERSION = "merge_analysis_v2_2_caption_foreground_assets_ready"
EXPECTED_SCOPE = "local_foreground_patch_intersecting_caption_region"


def load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Analysis JSON not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("Analysis JSON root must be an object")
    return payload


def atomic_save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(temp_path, path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Step 2E merge-analysis integration."
    )
    parser.add_argument("--analysis", required=True)
    parser.add_argument("--output-report", default="")
    parser.add_argument("--expected-span-count", type=int, default=1)
    parser.add_argument("--expected-frame-count", type=int, default=5)
    parser.add_argument("--expected-cue-id", default="sub_0052")
    args = parser.parse_args()

    analysis_path = Path(args.analysis)
    failures: List[str] = []

    try:
        analysis = load_json(analysis_path)
    except Exception as exc:
        result = {
            "ok": False,
            "validator_version": VALIDATOR_VERSION,
            "analysis_path": str(analysis_path),
            "failures": [f"analysis_load_failed:{type(exc).__name__}:{exc}"],
        }
        if args.output_report:
            atomic_save_json(Path(args.output_report), result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    if not analysis.get("success"):
        failures.append("analysis_success_false")
    if analysis.get("analysis_version") != EXPECTED_VERSION:
        failures.append(
            f"analysis_version_mismatch:{analysis.get('analysis_version')!r}"
        )
    if analysis.get("schema_version") != "2.1":
        failures.append(
            f"schema_version_mismatch:{analysis.get('schema_version')!r}"
        )
    if analysis.get("errors"):
        failures.append(f"analysis_errors:{len(analysis.get('errors') or [])}")

    summary = analysis.get("summary") or {}
    expected_summary = {
        "caption_foreground_assets_available": True,
        "caption_foreground_asset_spans_count": args.expected_span_count,
        "caption_foreground_editor_ready_spans_count": args.expected_span_count,
        "caption_foreground_rgba_frames_count": args.expected_frame_count,
        "caption_foreground_asset_linkage_ready": True,
        "caption_foreground_v4_ready": True,
    }
    for key, expected in expected_summary.items():
        actual = summary.get(key)
        if actual != expected:
            failures.append(f"summary_{key}:{actual!r}!={expected!r}")

    contract = analysis.get("caption_foreground_asset_contract") or {}
    for key in (
        "available",
        "success",
        "ready_for_merge_analysis",
        "ready_for_editor_compilers",
        "ready_for_v4_import",
    ):
        if not contract.get(key):
            failures.append(f"asset_contract_{key}_false")

    if contract.get("asset_span_count") != args.expected_span_count:
        failures.append("asset_contract_span_count_mismatch")
    if contract.get("editor_ready_span_count") != args.expected_span_count:
        failures.append("asset_contract_ready_span_count_mismatch")
    if contract.get("rgba_frames_count") != args.expected_frame_count:
        failures.append("asset_contract_rgba_frame_count_mismatch")
    if contract.get("asset_scope_required") != EXPECTED_SCOPE:
        failures.append("asset_contract_scope_mismatch")

    linkage = analysis.get("caption_foreground_asset_linkage") or {}
    if not linkage.get("ready"):
        failures.append("asset_linkage_not_ready")
    if not linkage.get("cue_linkage_complete"):
        failures.append("cue_linkage_incomplete")
    if linkage.get("orphan_asset_cue_ids"):
        failures.append("orphan_asset_cues_present")
    if linkage.get("missing_asset_cue_ids"):
        failures.append("missing_asset_cues_present")
    if args.expected_cue_id not in (linkage.get("foreground_asset_cue_ids") or []):
        failures.append("expected_cue_missing_from_asset_linkage")
    if args.expected_cue_id not in (linkage.get("approved_occlusion_cue_ids") or []):
        failures.append("expected_cue_missing_from_occlusion_linkage")

    timeline = analysis.get("timeline") or {}
    spans = timeline.get("caption_foreground_asset_spans") or []
    if len(spans) != args.expected_span_count:
        failures.append(f"timeline_span_count:{len(spans)}")

    total_span_frames = 0
    for span in spans:
        span_id = str(span.get("span_id") or "unknown_span")
        if not span.get("editor_ready"):
            failures.append(f"{span_id}:not_editor_ready")
        if span.get("asset_scope") != EXPECTED_SCOPE:
            failures.append(f"{span_id}:wrong_asset_scope")
        if span.get("errors"):
            failures.append(f"{span_id}:errors_present")
        if span.get("missing_rgba_frames"):
            failures.append(f"{span_id}:missing_rgba_frames")
        if span.get("missing_alpha_frames"):
            failures.append(f"{span_id}:missing_alpha_frames")
        if args.expected_cue_id not in (span.get("affected_cue_ids") or []):
            failures.append(f"{span_id}:expected_cue_missing")

        duration = int(span.get("duration_frames") or 0)
        total_span_frames += duration
        if duration <= 0:
            failures.append(f"{span_id}:invalid_duration")

        asset = span.get("rgba_asset") or {}
        if not asset.get("complete"):
            failures.append(f"{span_id}:rgba_asset_incomplete")
        if not ((asset.get("event_dir") or {}).get("is_dir")):
            failures.append(f"{span_id}:event_dir_missing")
        if not ((asset.get("manifest") or {}).get("is_file")):
            failures.append(f"{span_id}:manifest_missing")

        checks = span.get("file_checks") or []
        if len(checks) != duration:
            failures.append(f"{span_id}:file_check_count:{len(checks)}/{duration}")
        for check in checks:
            if not check.get("rgba_exists"):
                failures.append(f"{span_id}:rgba_missing:{check.get('timeline_frame')}")
            if not check.get("alpha_exists"):
                failures.append(f"{span_id}:alpha_missing:{check.get('timeline_frame')}")

    if total_span_frames != args.expected_frame_count:
        failures.append(
            f"timeline_total_span_frames:{total_span_frames}/{args.expected_frame_count}"
        )

    shots = timeline.get("shots") or []
    asset_shots = [
        shot
        for shot in shots
        if (shot.get("caption_foreground_assets") or {}).get("ready_for_v4_import")
    ]
    if not asset_shots:
        failures.append("no_shot_contains_ready_foreground_asset")

    overlap_frames = sum(
        int(span.get("overlap_duration_frames") or 0)
        for shot in asset_shots
        for span in ((shot.get("caption_foreground_assets") or {}).get("spans") or [])
    )
    if overlap_frames != args.expected_frame_count:
        failures.append(
            f"shot_overlap_frame_total:{overlap_frames}/{args.expected_frame_count}"
        )

    for shot in asset_shots:
        editor_contract = shot.get("editor_contract") or {}
        if not editor_contract.get("foreground_mask_ready"):
            failures.append("asset_shot_foreground_mask_ready_false")
        if not editor_contract.get("foreground_rgba_asset_ready"):
            failures.append("asset_shot_foreground_rgba_asset_ready_false")

    foreground_quality_flags = [
        flag
        for flag in (analysis.get("quality_flags") or [])
        if flag.get("layer") == "caption_foreground_assets"
        or "foreground_asset" in str(flag.get("type") or "")
    ]
    if foreground_quality_flags:
        failures.append(f"foreground_asset_quality_flags:{len(foreground_quality_flags)}")

    planner_ready = analysis.get("planner_ready") or {}
    recommended_inputs = planner_ready.get("recommended_inputs") or []
    required_inputs = {
        "timeline.caption_foreground_assets",
        "timeline.caption_foreground_asset_spans",
        "timeline.shots[].caption_foreground_assets",
        "caption_foreground_asset_contract",
        "caption_foreground_asset_linkage",
    }
    missing_planner_inputs = sorted(required_inputs - set(recommended_inputs))
    if missing_planner_inputs:
        failures.append("planner_inputs_missing:" + ",".join(missing_planner_inputs))

    rich = analysis.get("rich_generic_contract") or {}
    if not rich.get("caption_foreground_v4_ready"):
        failures.append("rich_contract_v4_ready_false")
    if not rich.get("caption_foreground_asset_linkage_ready"):
        failures.append("rich_contract_linkage_ready_false")

    result = {
        "ok": not failures,
        "validator_version": VALIDATOR_VERSION,
        "analysis_path": str(analysis_path),
        "analysis_version": analysis.get("analysis_version"),
        "schema_version": analysis.get("schema_version"),
        "asset_span_count": len(spans),
        "editor_ready_span_count": sum(1 for span in spans if span.get("editor_ready")),
        "rgba_frame_count": total_span_frames,
        "asset_shot_count": len(asset_shots),
        "asset_shot_overlap_frame_count": overlap_frames,
        "affected_cue_ids": linkage.get("foreground_asset_cue_ids") or [],
        "v4_ready": bool(summary.get("caption_foreground_v4_ready")),
        "quality_flags_count": len(analysis.get("quality_flags") or []),
        "failures": failures,
    }

    if args.output_report:
        output_path = Path(args.output_report)
        atomic_save_json(output_path, result)
        result["output_report"] = str(output_path)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result["ok"]:
        print(
            "PASS: Step 2E foreground RGBA assets are linked into "
            "analysis.json and ready for downstream planning."
        )

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
