#!/usr/bin/env python3
"""Validate first-pass/idempotency evidence for advanced flash replacement V2."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping

TASK_ID = "DZSQH7AUHJT_ADVANCED_TRANSITION_FLASH_REPLACEMENT_V2"
EXPECTED_TEXTPLUS_COUNT = 114
EXPECTED_FLASH_COUNT = 5
EXPECTED_FLASH_FRAMES = [96, 377, 426, 454, 758]
EXPECTED_STALE_DELETE_COUNT = 5


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def check_target(target: Mapping[str, Any]) -> Dict[str, bool]:
    captions = target.get("caption_snapshot") if isinstance(target.get("caption_snapshot"), Mapping) else {}
    flash = target.get("flash_snapshot") if isinstance(target.get("flash_snapshot"), Mapping) else {}
    stale = target.get("stale_transition_snapshot") if isinstance(target.get("stale_transition_snapshot"), Mapping) else {}
    rows = flash.get("rows") if isinstance(flash.get("rows"), list) else []
    starts = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("name") or "")
        try:
            cut = int(name.rsplit("_", 1)[-1])
        except ValueError:
            cut = -1
        starts.append(cut)
    return {
        "target_ok": target.get("ok") is True,
        "caption_count_114": int(captions.get("count") or 0) == EXPECTED_TEXTPLUS_COUNT,
        "caption_geometry_unchanged": target.get("caption_geometry_unchanged") is True,
        "media_geometry_unchanged": target.get("media_geometry_unchanged") is True,
        "unrelated_transitions_unchanged": target.get("unrelated_transitions_unchanged") is True,
        "stale_transitions_absent": target.get("stale_transitions_absent") is True and int(stale.get("count") or 0) == 0,
        "flash_count_5": int(flash.get("count") or 0) == EXPECTED_FLASH_COUNT,
        "flash_contract_ok": flash.get("ok") is True and all(isinstance(row, Mapping) and row.get("contract_ok") is True for row in rows),
        "flash_frames_exact": starts == EXPECTED_FLASH_FRAMES,
    }


def validate_report(report: Mapping[str, Any], expected_mode: str) -> Dict[str, Any]:
    checks: Dict[str, bool] = {
        "report_ok": report.get("ok") is True,
        "task_id": report.get("task_id") == TASK_ID,
        "run_mode": report.get("run_mode") == expected_mode,
        "expected_textplus_count": int(report.get("expected_textplus_count") or 0) == EXPECTED_TEXTPLUS_COUNT,
        "expected_flash_count": int(report.get("expected_flash_count") or 0) == EXPECTED_FLASH_COUNT,
        "expected_stale_delete_count": int(report.get("expected_stale_transition_delete_count") or 0) == EXPECTED_STALE_DELETE_COUNT,
        "source_timeline_unchanged": report.get("source_timeline_unchanged") is True,
    }
    target = report.get("target_after") if isinstance(report.get("target_after"), Mapping) else {}
    checks.update(check_target(target))
    if expected_mode == "apply":
        removal = report.get("stale_transition_removal") if isinstance(report.get("stale_transition_removal"), Mapping) else {}
        checks.update({
            "timeline_duplicate_once": int(report.get("timeline_duplicate_count") or 0) == 1,
            "five_stale_transitions_deleted": int(report.get("stale_transition_delete_count") or 0) == EXPECTED_STALE_DELETE_COUNT,
            "stale_removal_ok": removal.get("ok") is True,
            "stale_removal_media_unchanged": removal.get("media_geometry_unchanged") is True,
            "stale_removal_unrelated_transitions_unchanged": removal.get("unrelated_transitions_unchanged") is True,
            "video_track_added_once": int(report.get("video_track_add_count") or 0) == 1,
            "five_carriers_appended": int(report.get("flash_carrier_append_count") or 0) == EXPECTED_FLASH_COUNT,
            "five_fusion_flashes_configured": int(report.get("fusion_flash_configure_count") or 0) == EXPECTED_FLASH_COUNT,
            "save_once": int(report.get("save_call_count") or 0) == 1,
            "persistent_readback": report.get("persistent_readback_ok") is True,
            "visual_approval_required": report.get("visual_approval_required") is True,
        })
    else:
        checks.update({
            "idempotent": report.get("idempotent") is True,
            "timeline_duplicate_zero": int(report.get("timeline_duplicate_count") or 0) == 0,
            "stale_delete_zero": int(report.get("stale_transition_delete_count") or 0) == 0,
            "video_track_add_zero": int(report.get("video_track_add_count") or 0) == 0,
            "carrier_append_zero": int(report.get("flash_carrier_append_count") or 0) == 0,
            "fusion_configure_zero": int(report.get("fusion_flash_configure_count") or 0) == 0,
            "save_zero": int(report.get("save_call_count") or 0) == 0,
        })
    return {"checks": checks, "ok": all(checks.values())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--expected-mode", choices=["apply", "idempotency"], required=True)
    args = parser.parse_args()
    try:
        report_path = args.run_dir / "report.json"
        application_path = args.run_dir / "flash_transition_replacement.json"
        report = load_json(report_path)
        application = load_json(application_path)
        if report.get("run_id") != application.get("run_id") or report.get("task_id") != application.get("task_id"):
            raise ValueError("report_application_identity")
        result = validate_report(report, args.expected_mode)
        result.update({
            "task_id": TASK_ID,
            "run_id": report.get("run_id"),
            "expected_mode": args.expected_mode,
            "report_path": str(report_path),
            "application_path": str(application_path),
        })
        write_json(args.run_dir / f"{args.expected_mode}_validation.json", result)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
