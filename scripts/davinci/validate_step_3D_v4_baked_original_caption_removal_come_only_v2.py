#!/usr/bin/env python3
"""Validate the completed bounded baked-original caption-removal window."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping

TASK_ID = "DZSQH7AUHJT_STEP_3D_V4_BAKED_ORIGINAL_CAPTION_REMOVAL_COME_ONLY_V2"
SOURCE = (
    "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_"
    "repair_metrics_v1_occlusion_complete_v4_motion_fade_v1_the_size_fix_v1"
)
TARGET = SOURCE + "_baked_remove_come_only_v2"
EXPECTED_RANGE = [429, 453]
EXPECTED_TRACK = 2


def load(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def find_run(root: Path, run_id: str | None) -> Path:
    parent = root / ".agent" / "reports" / TASK_ID
    if run_id:
        path = parent / run_id
        if not path.is_dir():
            raise ValueError("run_dir")
        return path
    rows = sorted((path for path in parent.iterdir() if path.is_dir()), key=lambda path: path.name) if parent.is_dir() else []
    if len(rows) != 1:
        raise ValueError(f"run_count:{len(rows)}")
    return rows[0]


def validate(report: Mapping[str, Any], persistent: Mapping[str, Any], pixel: Mapping[str, Any], helper: Mapping[str, Any]) -> Dict[str, Any]:
    pchecks = persistent.get("checks") if isinstance(persistent.get("checks"), Mapping) else {}
    pixel_checks = pixel.get("checks") if isinstance(pixel.get("checks"), Mapping) else {}
    helper_checks = helper.get("checks") if isinstance(helper.get("checks"), Mapping) else {}
    required = {
        "runtime_ok": report.get("ok") is True,
        "source_exact": report.get("source_timeline_name") == SOURCE,
        "target_exact": report.get("target_timeline_name") == TARGET,
        "textplus_114": report.get("final_textplus_count") == 114,
        "zero_caption_mutation": report.get("caption_mutation_count") == 0,
        "one_baked_removal_mutation": report.get("baked_removal_mutation_count") == 1,
        "zero_occlusion_mutation": report.get("occlusion_mutation_count") == 0,
        "restore_track_2": report.get("restore_track") == EXPECTED_TRACK,
        "restore_range_exact": report.get("restore_range") == EXPECTED_RANGE,
        "one_save": report.get("save_call_count") == 1,
        "source_unchanged": report.get("source_timeline_unchanged") is True,
        "v4_occlusion_preserved": report.get("v4_occlusion_preserved") is True,
        "motion_fade_size_preserved": report.get("motion_fade_and_size_fix_preserved") is True,
        "persistent_flag": report.get("persistent_readback_ok") is True,
        "idempotency_flag": report.get("idempotency_ok") is True,
        "pre_save_pixel_flag": report.get("pre_save_pixel_authority_ok") is True,
        "target_retained": report.get("target_timeline_kept") is True,
        "persistent_ok": persistent.get("ok") is True,
        "persistent_checks_all": bool(pchecks) and all(value is True for value in pchecks.values()),
        "pixel_ok": pixel.get("ok") is True,
        "pixel_checks_all": bool(pixel_checks) and all(value is True for value in pixel_checks.values()),
        "pixel_sentinels_7_of_7": pixel.get("sentinel_pass_count") == 7 and pixel.get("sentinel_count") == 7,
        "helper_ok": helper.get("ok") is True,
        "helper_checks_all": bool(helper_checks) and all(value is True for value in helper_checks.values()),
        "helper_range": helper.get("clean_range") == EXPECTED_RANGE,
        "visual_gate_required": report.get("visual_approval_required") is True and persistent.get("visual_approval_required") is True,
        "rollout_locked": report.get("further_rollout_authorized") is False and persistent.get("further_rollout_authorized") is False,
    }
    return {"schema_version": 1, "task_id": TASK_ID, "ok": all(required.values()), "checks": required}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id")
    args = parser.parse_args()
    try:
        run = find_run(args.root.resolve(), args.run_id)
        result = validate(
            load(run / "report.json"),
            load(run / "persistent_readback.json"),
            load(run / "pre_save_pixel_validation.json"),
            load(run / "generated_baked_removal_come_v2" / "manifest.json"),
        )
        (run / "technical_validation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "task_id": TASK_ID, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
