"""Offline validator for Reel #1 completed-Flash idempotency evidence."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

TASK_ID = "VIDEO_CLONER_PHASE5_REEL1_FLASH_IDEMPOTENCY_V1"
MODE = "phase5_reel1_flash_v4_idempotency"
TARGET = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1_occlusion_complete_v4_flash_transition_v4"
HISTORICAL = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1_occlusion_complete_v3"
MEDIA_UID = "c76c02be-4263-4ae2-a948-7279407de5ed"
SPANS = ((94, 98), (375, 379), (424, 428), (452, 456), (756, 760))
ZERO_MUTATIONS = {"media_imports": 0, "timeline_appends": 0, "timeline_item_deletes": 0, "media_pool_deletes": 0,
                  "video_track_creates": 0, "fusion_configures": 0, "fusion_deletes": 0, "item_renames": 0,
                  "media_writes": 0, "timeline_selections": 0, "project_saves": 0}


def validate(root: Path, run_id: str) -> dict:
    path = root / ".agent/reports" / TASK_ID / run_id / "report.json"
    if not path.is_file():
        return {"ok": False, "failures": ["missing:report.json"]}
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    failures = []
    if report.get("task_id") != TASK_ID or report.get("mode") != MODE or report.get("run_id") != run_id:
        failures.append("identity")
    if (report.get("ok") is not True or report.get("classification") != "RELINKED_FLASH_ALREADY_COMPLETE"
            or report.get("idempotent") is not True or report.get("carriers_reused") != 5 or report.get("failures")):
        failures.append("classification")
    if report.get("mutation_counts") != ZERO_MUTATIONS or report.get("save_project_count") != 0:
        failures.append("zero_mutations")
    before, after = report.get("completed_state_before") or {}, report.get("completed_state_after") or {}
    if (before != after or before.get("classification") != "VALID_RELINKED_FLASH_COMPLETE_STATE"
            or before.get("ok") is not True or before.get("count") != 5 or before.get("duplicate_count") != 0
            or before.get("zero_fusion_count") != 0 or before.get("partial_count") != 0):
        failures.append("completed_state")
    flash = before.get("flash_v4") or {}
    if flash.get("ok") is not True or flash.get("neutral_carrier_count") != 5 or flash.get("source_video_carrier_count") != 0:
        failures.append("flash_v4")
    rows = before.get("rows") or []
    expected = [(26, start, end, f"VC_FLASH_{index:03d}_frame_{start + 2:04d}", MEDIA_UID, 1)
                for index, (start, end) in enumerate(SPANS, 1)]
    actual = [(row.get("track_index"), row.get("start"), row.get("end"), row.get("name"), row.get("media_uid"), row.get("fusion_comp_count")) for row in rows]
    if actual != expected:
        failures.append("carrier_contract")
    if (report.get("carrier_uids_before") != report.get("carrier_uids_after")
            or len(set(report.get("carrier_uids_after") or [])) != 5):
        failures.append("carrier_uids")
    if (report.get("target_snapshot_before") != report.get("target_snapshot_after")
            or report.get("neutral_media_before") != report.get("neutral_media_after")
            or report.get("neutral_media_references_before") != report.get("neutral_media_references_after")
            or report.get("non_target_timelines_unchanged") is not True
            or report.get("current_timeline_before") != report.get("current_timeline_after")):
        failures.append("no_op_readback")
    references = report.get("neutral_media_references_after") or []
    geometry = Counter((row.get("timeline"), row.get("track_index"), row.get("start"), row.get("end"), row.get("fusion_comp_count")) for row in references)
    expected_refs = Counter([(HISTORICAL, 25, 426, 454, 0)] + [(TARGET, 26, start, end, 1) for start, end in SPANS])
    if geometry != expected_refs or (report.get("neutral_media_after") or {}).get("unique_id") != MEDIA_UID:
        failures.append("shared_media_protection")
    rollback = report.get("rollback") or {}
    if rollback != {"safe": True, "state": "complete_state_unmodified", "attempted": False}:
        failures.append("rollback_state")
    return {"ok": not failures, "run_id": run_id, "failures": failures,
            "classification": "PASS_PHASE5_REEL1_FLASH_IDEMPOTENCY" if not failures else "FAIL_PHASE5_REEL1_FLASH_IDEMPOTENCY"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result = validate(args.root, args.run_id)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["ok"] else 1)
