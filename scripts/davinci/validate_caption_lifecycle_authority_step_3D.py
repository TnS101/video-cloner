#!/usr/bin/env python3
"""Validate a visual-first caption lifecycle authority plan."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

EXPECTED_QUEUE = ["sub_052", "sub_057", "sub_058", "sub_081"]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def load_planner(path: Path):
    spec = importlib.util.spec_from_file_location("caption_lifecycle_planner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could_not_load_planner:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate(
    planner_path: Path,
    visual_tracks_path: Path,
    caption_plan_path: Path,
    plan_path: Path,
) -> dict[str, Any]:
    planner = load_planner(planner_path)
    visual = load_json(visual_tracks_path)
    captions = load_json(caption_plan_path)
    actual = load_json(plan_path)
    expected = planner.build_plan(visual, captions)

    summary = actual.get("summary") or {}
    layers = actual.get("layers") or []
    layer_by_cue = {
        str(row.get("cue_id") or ""): row
        for row in layers
        if isinstance(row, dict)
    }
    checks = {
        "plan_exact_reproduction": actual == expected,
        "plan_ok": actual.get("ok") is True,
        "schema": actual.get("schema") == planner.SCHEMA,
        "authority_policy": actual.get("authority_policy") == planner.AUTHORITY_POLICY,
        "caption_layer_count": summary.get("caption_layer_count") == 116,
        "visual_primary_count": summary.get("visual_primary_count") == 45,
        "transcript_fallback_count": summary.get("transcript_fallback_count") == 71,
        "visual_differs_from_transcript_count": summary.get("visual_differs_from_transcript_count") == 44,
        "visual_extends_outside_transcript_count": summary.get("visual_extends_outside_transcript_count") == 41,
        "visual_fully_contained_count": summary.get("visual_fully_contained_count") == 4,
        "visual_concurrent_overlap_pair_count": summary.get("visual_concurrent_overlap_pair_count") == 31,
        "selected_animation_count": summary.get("selected_animation_count") == 8,
        "selected_animation_visual_primary_count": summary.get("selected_animation_visual_primary_count") == 4,
        "selected_animation_missing_visual_lifecycle_count": summary.get("selected_animation_missing_visual_lifecycle_count") == 4,
        "mandatory_redetection_queue": summary.get("mandatory_redetection_cue_ids") == EXPECTED_QUEUE,
        "come_requires_visual_redetection": (
            (layer_by_cue.get("sub_052") or {}).get("text") == "COME"
            and (layer_by_cue.get("sub_052") or {}).get("timing_authority") == "transcript_fallback"
            and (layer_by_cue.get("sub_052") or {}).get("requires_visual_lifecycle_redetection") is True
            and (layer_by_cue.get("sub_052") or {}).get("calibration_priority") == "mandatory"
        ),
        "transcript_text_primary": all(
            row.get("text_authority") == "transcript_primary"
            for row in layers
            if isinstance(row, dict)
        ),
        "visual_life_not_clamped": all(
            row.get("timing_authority") != "visual_primary"
            or row.get("lifecycle_status") == "source_observed"
            for row in layers
            if isinstance(row, dict)
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "ok": not failures,
        "schema": "video_cloner_caption_lifecycle_authority_validation",
        "schema_version": 1,
        "plan_path": str(plan_path),
        "summary": summary,
        "checks": checks,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--planner", type=Path, required=True)
    parser.add_argument("--visual-tracks", type=Path, required=True)
    parser.add_argument("--caption-plan", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate(
            args.planner,
            args.visual_tracks,
            args.caption_plan,
            args.plan,
        )
        write_json(args.output, result)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
