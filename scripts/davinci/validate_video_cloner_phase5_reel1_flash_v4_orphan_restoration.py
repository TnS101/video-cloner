"""Offline validator for in-place Reel #1 flash restoration evidence."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

TASK_ID = "VIDEO_CLONER_PHASE5_REEL1_RELINKED_FLASH_INPLACE_RESTORATION_V1"
MODE = "phase5_reel1_relinked_flash_inplace_restoration"
TARGET = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1_occlusion_complete_v4_flash_transition_v4"
HISTORICAL = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1_occlusion_complete_v3"
MEDIA_UID = "c76c02be-4263-4ae2-a948-7279407de5ed"
SPANS = ((94, 98), (375, 379), (424, 428), (452, 456), (756, 760))
EXPECTED_MUTATIONS = {"media_imports": 0, "timeline_appends": 0, "timeline_item_deletes": 0, "media_pool_deletes": 0,
                      "video_track_creates": 0, "fusion_configures": 5, "item_renames": 5, "project_saves": 1}


def validate(root: Path, run_id: str) -> dict:
    path = root / ".agent/reports" / TASK_ID / run_id / "report.json"
    if not path.is_file():
        return {"ok": False, "failures": ["missing:report.json"]}
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    failures = []
    if report.get("task_id") != TASK_ID or report.get("mode") != MODE or report.get("run_id") != run_id:
        failures.append("identity")
    if report.get("ok") is not True or report.get("classification") != "RELINKED_INPLACE_FLASH_RESTORED" or report.get("duplicate_count") != 0 or report.get("failures"):
        failures.append("classification")
    if report.get("mutation_counts") != EXPECTED_MUTATIONS or report.get("save_project_count") != 1:
        failures.append("bounded_mutations")
    pre = report.get("prestate") or {}
    if pre.get("classification") != "RELINKED_ZERO_FUSION_PRESTATE" or pre.get("ok") is not True or pre.get("count") != 5:
        failures.append("prestate")
    flash = report.get("flash_after") or {}
    if flash.get("ok") is not True or flash.get("neutral_carrier_count") != 5 or flash.get("source_video_carrier_count") != 0:
        failures.append("flash_readback")
    if report.get("carrier_invariants_unchanged") is not True or report.get("non_target_timelines_unchanged") is not True or report.get("unaffected_target_signature_before") != report.get("unaffected_target_signature_after"):
        failures.append("timeline_protection")
    carrier_keys = ("item_uid", "track_index", "start", "end", "duration", "media_uid", "media_name", "media_path")
    carriers_before = report.get("carriers_before") or []
    carriers_after = report.get("carriers_after") or []
    if len(carriers_before) != 5 or len(carriers_after) != 5 or [[row.get(key) for key in carrier_keys] for row in carriers_before] != [[row.get(key) for key in carrier_keys] for row in carriers_after]:
        failures.append("carrier_invariants")
    before = report.get("neutral_media_references_before") or []
    after = report.get("neutral_media_references_after") or []
    before_geometry = Counter((row.get("timeline"), row.get("track_index"), row.get("start"), row.get("end"), row.get("media_uid")) for row in before)
    after_geometry = Counter((row.get("timeline"), row.get("track_index"), row.get("start"), row.get("end"), row.get("media_uid")) for row in after)
    expected = Counter([(HISTORICAL, 25, 426, 454, MEDIA_UID)] + [(TARGET, 26, start, end, MEDIA_UID) for start, end in SPANS])
    if before_geometry != expected or after_geometry != expected:
        failures.append("shared_media_references")
    historical_before = [row for row in before if row.get("timeline") == HISTORICAL]
    historical_after = [row for row in after if row.get("timeline") == HISTORICAL]
    if historical_before != historical_after or len(historical_after) != 1 or historical_after[0].get("fusion_comp_count") != 0:
        failures.append("historical_protection")
    if report.get("neutral_media_before") != report.get("neutral_media_after") or (report.get("neutral_media_after") or {}).get("unique_id") != MEDIA_UID:
        failures.append("media_pool_protection")
    rollback = report.get("rollback") or {}
    if rollback.get("safe") is not True or rollback.get("attempted") is not False or rollback.get("state") != "restored_valid_state":
        failures.append("rollback_state")
    if (report.get("previous_current_timeline_restoration") or {}).get("ok") is not True:
        failures.append("current_timeline_restoration")
    return {"ok": not failures, "run_id": run_id, "failures": failures,
            "classification": "PASS_RELINKED_INPLACE_RESTORATION" if not failures else "FAIL_RELINKED_INPLACE_RESTORATION"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result = validate(args.root, args.run_id)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["ok"] else 1)
