#!/usr/bin/env python3
"""Validate targeted visual lifecycle redetection and calibrated authority plan."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

EXPECTED_CUES = ["sub_052", "sub_057", "sub_058", "sub_081"]


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


def validate(redetection_path: Path, calibrated_path: Path, debug_dir: Path) -> dict[str, Any]:
    redetection = load_json(redetection_path)
    calibrated = load_json(calibrated_path)
    detections = [row for row in redetection.get("detections") or [] if isinstance(row, dict)]
    detection_by_cue = {str(row.get("cue_id") or ""): row for row in detections}
    layers = [row for row in calibrated.get("layers") or [] if isinstance(row, dict)]
    layer_by_cue = {str(row.get("cue_id") or ""): row for row in layers}
    summary = calibrated.get("summary") or {}

    contact_sheets = [debug_dir / "contact_sheets" / f"{cue}_lifecycle_contact_sheet.jpg" for cue in EXPECTED_CUES]
    checks = {
        "redetection_ok": redetection.get("ok") is True,
        "target_cues": redetection.get("target_cue_ids") == EXPECTED_CUES,
        "resolved_all_four": redetection.get("resolved_cue_count") == 4 and redetection.get("unresolved_cue_count") == 0,
        "unique_detection_cues": list(detection_by_cue) == EXPECTED_CUES,
        "source_video_original": bool(redetection.get("source_video_sha256")),
        "timeline_read_only": redetection.get("timeline_modified") is False,
        "no_resolve_bridge": redetection.get("resolve_invoked") is False and redetection.get("bridge_invoked") is False,
        "all_lifecycle_windows_valid": all(
            isinstance((detection_by_cue.get(cue) or {}).get("lifecycle_window"), list)
            and len((detection_by_cue.get(cue) or {}).get("lifecycle_window")) == 2
            and (detection_by_cue[cue]["lifecycle_window"][1] > detection_by_cue[cue]["lifecycle_window"][0])
            for cue in EXPECTED_CUES
        ),
        "visual_timing_authority": all(
            detection_by_cue[cue].get("timing_authority")
            == "visual_primary_targeted_redetection"
            for cue in EXPECTED_CUES
        ),
        "come_persistence_detected": (
            detection_by_cue.get("sub_052", {}).get("ends_after_transcript_frames", 0) > 0
        ),
        "contact_sheets_exist": all(path.is_file() and path.stat().st_size > 0 for path in contact_sheets),
        "calibrated_ok": calibrated.get("ok") is True,
        "calibrated_caption_count": summary.get("caption_layer_count") == 116,
        "visual_primary_count": summary.get("visual_primary_count") == 49,
        "transcript_fallback_count": summary.get("transcript_fallback_count") == 67,
        "all_animated_visual_primary": summary.get("selected_animation_visual_primary_count") == 8,
        "no_animated_missing_lifecycle": summary.get("selected_animation_missing_visual_lifecycle_count") == 0,
        "mandatory_queue_empty": summary.get("mandatory_redetection_count") == 0 and calibrated.get("mandatory_visual_redetection_queue") == [],
        "calibrated_targets_match": all(
            (layer_by_cue.get(cue) or {}).get("timing_authority") == "visual_primary_redetected"
            and (layer_by_cue.get(cue) or {}).get("lifecycle_window") == detection_by_cue[cue].get("lifecycle_window")
            for cue in EXPECTED_CUES
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "ok": not failures,
        "schema": "video_cloner_caption_lifecycle_redetection_validation",
        "schema_version": 1,
        "redetection_path": str(redetection_path),
        "calibrated_plan_path": str(calibrated_path),
        "target_cue_ids": EXPECTED_CUES,
        "summary": summary,
        "checks": checks,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--redetection", type=Path, required=True)
    parser.add_argument("--calibrated-plan", type=Path, required=True)
    parser.add_argument("--debug-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate(args.redetection, args.calibrated_plan, args.debug_dir)
        write_json(args.output, result)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
