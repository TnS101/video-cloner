#!/usr/bin/env python3
"""Validate one completed size-only `the` correction from persistent evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping

TASK_ID = "DZSQH7AUHJT_CAPTION_THE_SIZE_POP_FIX_V1"
SOURCE = (
    "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_"
    "repair_metrics_v1_occlusion_complete_v4_motion_fade_v1"
)
TARGET = SOURCE + "_the_size_fix_v1"


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
    rows = sorted([p for p in parent.iterdir() if p.is_dir()], key=lambda p: p.name) if parent.is_dir() else []
    if len(rows) != 1:
        raise ValueError(f"run_count:{len(rows)}")
    return rows[0]


def validate(report: Mapping[str, Any], persistent: Mapping[str, Any]) -> Dict[str, Any]:
    checks = persistent.get("checks") if isinstance(persistent.get("checks"), Mapping) else {}
    required = {
        "runtime_ok": report.get("ok") is True,
        "source_exact": report.get("source_timeline_name") == SOURCE,
        "target_exact": report.get("target_timeline_name") == TARGET,
        "textplus_114": report.get("final_textplus_count") == 114,
        "exact_two_targets": report.get("target_caption_count") == 2,
        "exact_21_size_keys": report.get("size_key_write_count") == 21,
        "exact_two_size_properties": report.get("mutated_property_count") == 2,
        "no_recreation": report.get("caption_recreation_count") == 0,
        "no_center_write": report.get("center_write_count") == 0,
        "no_opacity_write": report.get("opacity_write_count") == 0,
        "no_style_write": report.get("style_write_count") == 0,
        "no_timing_track_mutation": report.get("timing_track_mutation_count") == 0,
        "no_occlusion_mutation": report.get("occlusion_mutation_count") == 0,
        "one_save": report.get("save_call_count") == 1,
        "source_unchanged": report.get("source_timeline_unchanged") is True,
        "motion_fade_preserved": report.get("motion_fade_source_preserved_except_target_size") is True,
        "v4_occlusion_preserved": report.get("v4_occlusion_preserved") is True,
        "persistent_flag": report.get("persistent_readback_ok") is True,
        "idempotency_flag": report.get("idempotency_ok") is True,
        "persistent_ok": persistent.get("ok") is True,
        "persistent_checks_all": bool(checks) and all(value is True for value in checks.values()),
        "visual_gate_required": report.get("visual_approval_required") is True and persistent.get("visual_approval_required") is True,
        "rollout_locked": report.get("further_rollout_authorized") is False and persistent.get("further_rollout_authorized") is False,
    }
    return {"ok": all(required.values()), "checks": required}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id")
    args = parser.parse_args()
    try:
        run = find_run(args.root.resolve(), args.run_id)
        report = load(run / "report.json")
        persistent = load(run / "persistent_readback.json")
        result = validate(report, persistent)
        (run / "technical_validation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
