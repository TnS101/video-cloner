"""Validate and reuse the already-complete Reel #1 Flash V4 state without mutation."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RESTORE = _load("vc_reel1_restore", HERE / "video_cloner_phase5_reel1_flash_v4_orphan_restoration.py")
V1, V4, P4B, BASE = RESTORE.V1, RESTORE.V4, RESTORE.P4B, RESTORE.BASE
TASK_ID = "VIDEO_CLONER_PHASE5_REEL1_FLASH_IDEMPOTENCY_V1"
MODE = "phase5_reel1_flash_v4_idempotency"
PROJECT_NAME = RESTORE.PROJECT_NAME
TARGET_TIMELINE_NAME = RESTORE.TARGET_TIMELINE_NAME
EXPECTED_TRACK = RESTORE.EXPECTED_TRACK
EXPECTED_SPANS = RESTORE.EXPECTED_SPANS
EXPECTED_MEDIA_UID = RESTORE.EXPECTED_MEDIA_UID
EXPECTED_MEDIA_PATH = RESTORE.EXPECTED_MEDIA_PATH
EXPECTED_PLAN_SHA256 = RESTORE.EXPECTED_PLAN_SHA256
EXPECTED_COMPLETE_SIGNATURE = "2e6b47f8a89e446e5caf87e756e20bdd3399c011f0a1803575909a233d670810"
EXPECTED_RESTORATION_SHA256 = "23FD0E963532152E854DF5943F26386754C01CAF817AE4B7DE73A42347193EA8"
EXPECTED_PERSISTENCE_SHA256 = "505BC16DB5D7D858F4DFFAD57B1887E4FB23108B9ED3BBBF2398ED20AFF107C2"
ZERO_MUTATIONS = {
    "media_imports": 0, "timeline_appends": 0, "timeline_item_deletes": 0,
    "media_pool_deletes": 0, "video_track_creates": 0, "fusion_configures": 0,
    "fusion_deletes": 0, "item_renames": 0, "media_writes": 0,
    "timeline_selections": 0, "project_saves": 0,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _report(root: Path, contract: Mapping[str, Any], expected_hash: str) -> dict[str, Any]:
    path = (root / Path(str(contract.get("path") or ""))).resolve()
    if root.resolve() not in path.parents or not path.is_file():
        raise ValueError("prerequisite_path")
    declared = str(contract.get("sha256") or "").upper()
    if declared != expected_hash or _sha256(path) != declared:
        raise ValueError("prerequisite_hash")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _load_prerequisites(root: Path, payload: Mapping[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    restored = _report(root, payload.get("restoration_report") or {}, EXPECTED_RESTORATION_SHA256)
    if (restored.get("ok"), restored.get("classification"), restored.get("duplicate_count")) != (True, "RELINKED_INPLACE_FLASH_RESTORED", 0):
        raise ValueError("restoration_contract")
    carriers = restored.get("carriers_after") or []
    geometry = [(row.get("track_index"), row.get("start"), row.get("end"), row.get("fusion_comp_count"), row.get("media_uid")) for row in carriers]
    expected_geometry = [(EXPECTED_TRACK, start, end, 1, EXPECTED_MEDIA_UID) for start, end in EXPECTED_SPANS]
    item_uids = [str(row.get("item_uid") or "") for row in carriers]
    if geometry != expected_geometry or len(set(item_uids)) != 5 or not all(item_uids):
        raise ValueError("restoration_carriers")

    persistence = _report(root, payload.get("persistence_report") or {}, EXPECTED_PERSISTENCE_SHA256)
    if (persistence.get("ok") is not True or persistence.get("read_only") is not True
            or persistence.get("read_determinism_classification") != "TIMELINE_SIGNATURES_STABLE_TWO_PASS"
            or persistence.get("signature_mismatches") or any((persistence.get("mutation_counts") or {}).values())):
        raise ValueError("persistence_contract")
    state = persistence.get("reel1_restoration_state") or {}
    spans = state.get("spans") or []
    if (state.get("classification_counts") != {"VALID_REPLACEMENT_PRESENT": 5}
            or state.get("timeline_signature") != EXPECTED_COMPLETE_SIGNATURE
            or [(row.get("start"), row.get("end"), row.get("classification")) for row in spans]
            != [(start, end, "VALID_REPLACEMENT_PRESENT") for start, end in EXPECTED_SPANS]):
        raise ValueError("persistence_target_state")
    neutral = persistence.get("neutral_media") or {}
    objects = neutral.get("objects") or []
    reel2 = persistence.get("reel2_protection_state") or {}
    if (neutral.get("classification") != "NEUTRAL_MEDIA_SINGLE_SHARED_OBJECT" or neutral.get("count") != 1
            or len(objects) != 1 or objects[0].get("unique_id") != EXPECTED_MEDIA_UID
            or reel2.get("ok") is not True or not all((reel2.get("checks") or {}).values())
            or reel2.get("timeline_signature") != RESTORE.EXPECTED_REEL2_SIGNATURE):
        raise ValueError("persistence_protection_state")
    inventory = [{"name": row.get("timeline_name"), "signature": (row.get("snapshot") or {}).get("signature")}
                 for row in (persistence.get("signature_pass_b") or {}).get("timelines", [])]
    expected = {row["name"]: row["signature"] for row in inventory}
    if (len(inventory) != 29 or expected.get(TARGET_TIMELINE_NAME) != EXPECTED_COMPLETE_SIGNATURE
            or expected.get(RESTORE.HISTORICAL_TIMELINE_NAME) != RESTORE.EXPECTED_HISTORICAL_SIGNATURE
            or expected.get(RESTORE.REEL2_TIMELINE_NAME) != RESTORE.EXPECTED_REEL2_SIGNATURE):
        raise ValueError("persistence_inventory")
    return item_uids, inventory


def _require_inventory(expected: Sequence[Mapping[str, Any]], actual: Sequence[Mapping[str, Any]]) -> None:
    key = lambda row: (row.get("name"), row.get("signature"))
    if Counter(map(key, expected)) != Counter(map(key, actual)):
        raise RuntimeError("live_inventory_drift")


def validate_complete_state(timeline: Any, flashes: Sequence[Mapping[str, Any]], expected_uids: Sequence[str]) -> dict[str, Any]:
    rows = RESTORE._target_candidates(timeline)
    errors = []
    names = [str(row.get("name") or "") for row in flashes]
    if len(rows) != 5 or [(row["start"], row["end"]) for row in rows] != list(EXPECTED_SPANS):
        errors.append("carrier_cardinality_or_span")
    for index, row in enumerate(rows):
        if row["track_index"] != EXPECTED_TRACK or row["duration"] != 4:
            errors.append(f"carrier_geometry:{row['start']}")
        if index >= len(names) or row["name"] != names[index] or row["item_uid"] != expected_uids[index]:
            errors.append(f"carrier_identity:{row['start']}")
        if (row["media_uid"] != EXPECTED_MEDIA_UID or row["media_name"] != RESTORE.EXPECTED_MEDIA_NAME
                or not P4B.same_path(row["media_path"], EXPECTED_MEDIA_PATH)):
            errors.append(f"carrier_media:{row['start']}")
        if row["fusion_comp_count"] != 1 or len(row["fusion_comp_names"]) != 1:
            errors.append(f"carrier_fusion:{row['start']}")
    flash = V4.neutral_flash_snapshot(timeline, flashes, EXPECTED_TRACK)
    if not flash.get("ok") or flash.get("neutral_carrier_count") != 5 or flash.get("source_video_carrier_count") != 0:
        errors.append("flash_v4_contract")
    return {
        "ok": not errors,
        "classification": "VALID_RELINKED_FLASH_COMPLETE_STATE" if not errors else "COMPLETE_STATE_MISMATCH",
        "errors": errors,
        "count": len(rows),
        "duplicate_count": max(0, len(rows) - 5),
        "zero_fusion_count": sum(row["fusion_comp_count"] == 0 for row in rows),
        "partial_count": sum(row["fusion_comp_count"] != 1 for row in rows),
        "rows": [RESTORE._public(row) for row in rows],
        "flash_v4": flash,
    }


def run(resolve: Any, context: Mapping[str, Any]) -> dict[str, Any]:
    command = context.get("command") or {}
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    report: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "mode": MODE, "run_id": run_id,
                              "classification": "FAILED_CLOSED", "mutation_counts": dict(ZERO_MUTATIONS), "failures": []}
    try:
        if command.get("task") != TASK_ID or command.get("mode") != MODE or not run_id:
            raise ValueError("command_identity")
        payload = command.get("payload") or {}
        if payload.get("expected_project") != PROJECT_NAME or payload.get("target_timeline_name") != TARGET_TIMELINE_NAME or payload.get("read_only") is not False:
            raise ValueError("target_identity")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        plan = payload.get("accepted_plan") or {}
        BASE.validate_plan(plan)
        if str(payload.get("accepted_plan_file_sha256") or "").upper() != EXPECTED_PLAN_SHA256:
            raise ValueError("accepted_plan_file_hash")
        flashes = list(plan.get("flashes") or [])
        if [(int(row.get("start_frame", -1)), int(row.get("start_frame", -1)) + int(row.get("duration_frames", -1))) for row in flashes] != list(EXPECTED_SPANS):
            raise ValueError("accepted_plan_geometry")
        expected_uids, expected_inventory = _load_prerequisites(root, payload)
        manager = V1.safe_call(resolve, "GetProjectManager", default=None)
        project = V1.safe_call(manager, "GetCurrentProject", default=None)
        if project is None or V1.safe_call(project, "GetName", default="") != PROJECT_NAME:
            raise RuntimeError("project_identity")
        current_before = P4B.timeline_name(V1.safe_call(project, "GetCurrentTimeline", default=None))
        timeline = BASE.find_one(project, TARGET_TIMELINE_NAME)
        inventory_before, _ = BASE.non_target_inventory(project, TARGET_TIMELINE_NAME)
        _require_inventory(expected_inventory, inventory_before)
        snapshot_before = P4B.timeline_snapshot(timeline)
        if snapshot_before.get("signature") != EXPECTED_COMPLETE_SIGNATURE:
            raise RuntimeError("target_complete_signature")
        state_before = validate_complete_state(timeline, flashes, expected_uids)
        if not state_before["ok"]:
            raise RuntimeError("complete_state")
        media_pool = V1.safe_call(project, "GetMediaPool", default=None)
        media_before, references_before = RESTORE._media_and_references(project, media_pool, configured=True)

        inventory_after, _ = BASE.non_target_inventory(project, TARGET_TIMELINE_NAME)
        _require_inventory(inventory_before, inventory_after)
        snapshot_after = P4B.timeline_snapshot(timeline)
        state_after = validate_complete_state(timeline, flashes, expected_uids)
        media_after, references_after = RESTORE._media_and_references(project, media_pool, configured=True)
        current_after = P4B.timeline_name(V1.safe_call(project, "GetCurrentTimeline", default=None))
        if (snapshot_after != snapshot_before or state_after != state_before or media_after != media_before
                or references_after != references_before or current_after != current_before):
            raise RuntimeError("idempotency_readback_drift")
        report.update({
            "ok": True, "classification": "RELINKED_FLASH_ALREADY_COMPLETE", "idempotent": True,
            "completed_state_before": state_before, "completed_state_after": state_after,
            "carriers_reused": 5, "carrier_uids_before": list(expected_uids), "carrier_uids_after": list(expected_uids),
            "target_snapshot_before": snapshot_before, "target_snapshot_after": snapshot_after,
            "neutral_media_before": media_before, "neutral_media_after": media_after,
            "neutral_media_references_before": references_before, "neutral_media_references_after": references_after,
            "non_target_timelines_unchanged": True, "current_timeline_before": current_before,
            "current_timeline_after": current_after, "save_project_count": 0, "duplicate_count": 0,
            "rollback": {"safe": True, "state": "complete_state_unmodified", "attempted": False},
        })
    except BaseException as exc:
        report["failures"] = [f"{type(exc).__name__}: {exc}"]
        report["traceback"] = traceback.format_exc()
        report["rollback"] = {"safe": True, "state": "unmutated_validation_failure", "attempted": False}
    return report
