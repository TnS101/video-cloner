"""Restore five already-relinked Reel #1 flash carriers in place."""
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


V4 = _load("vc_inplace_v4", HERE / "advanced_transition_flash_neutral_rgba_v4.py")
V1 = V4.V1
P4B = _load("vc_inplace_p4b", HERE / "video_cloner_phase4b_timeline_application.py")
BASE = _load("vc_inplace_base", HERE / "video_cloner_phase4c1_flash_v4_integration.py")
PROBE = _load("vc_inplace_probe", HERE / "video_cloner_phase4c1_post_rollback_readonly_probe.py")

TASK_ID = "VIDEO_CLONER_PHASE5_REEL1_RELINKED_FLASH_INPLACE_RESTORATION_V1"
MODE = "phase5_reel1_relinked_flash_inplace_restoration"
PROJECT_NAME = "New Project 1"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1_occlusion_complete_v4_flash_transition_v4"
HISTORICAL_TIMELINE_NAME = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1_occlusion_complete_v3"
REEL2_TIMELINE_NAME = "DcJRJtUKScu_standalone_timeline"
EXPECTED_TRACK = 26
EXPECTED_SPANS = ((94, 98), (375, 379), (424, 428), (452, 456), (756, 760))
EXPECTED_MEDIA_NAME = V4.NEUTRAL_MEDIA_POOL_ITEM_NAME
EXPECTED_MEDIA_UID = "c76c02be-4263-4ae2-a948-7279407de5ed"
EXPECTED_MEDIA_PATH = r"C:\Users\User\Downloads\Projects\Video Cloner\data\DZsqH7auhjt\davinci\flash_neutral_rgba_v4\rgba_[000000-000003].png"
EXPECTED_PRESTATE_SIGNATURE = "f9624bbed3b87447a01e961f2444cdac4f63963a2a6eac830af81cdf65f829c0"
EXPECTED_HISTORICAL_SIGNATURE = "63784994e171b42c481c1a954732cd9bfe673d9adcf544685ba2ec565fc5e129"
EXPECTED_REEL2_SIGNATURE = "ba19fff1bc7ffc7e8555983ed5a08621e4f338dc1dc278385d7981435db17fe1"
EXPECTED_PLAN_SHA256 = "39FCD4B29289632B110716843EF37E5208D5CBEEB2B03EA64EBE587C57B31443"
EXPECTED_PREREQUISITE_SHA256 = "F73798C65BF9A38705464CCE9E8960410BBA8F72B554C3E951F112E781F2024D"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _comp_names(item: Any) -> list[str]:
    return [str(value) for value in (V1.safe_call(item, "GetFusionCompNameList", default=[]) or [])]


def _carrier_row(track: int, item: Any) -> dict[str, Any]:
    media = V1.safe_call(item, "GetMediaPoolItem", default=None)
    media_row = PROBE._media_row(media) if media is not None else {}
    return {
        "item": item,
        "item_uid": V1.item_uid(item),
        "track_index": track,
        "start": V1.item_start(item),
        "end": V1.item_end(item),
        "duration": V1.item_duration(item),
        "name": V1.item_name(item),
        "media_uid": media_row.get("unique_id"),
        "media_name": media_row.get("name"),
        "media_path": media_row.get("resolved_path") or "",
        "fusion_comp_count": int(V1.safe_call(item, "GetFusionCompCount", default=0) or 0),
        "fusion_comp_names": _comp_names(item),
    }


def _public(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "item"}


def _target_candidates(timeline: Any) -> list[dict[str, Any]]:
    rows = []
    for track, item in V1.all_video_items(timeline):
        row = _carrier_row(track, item)
        if track == EXPECTED_TRACK or row["name"].startswith(V1.FLASH_PREFIX) or "flash_neutral_rgba_v4" in row["media_path"].lower():
            rows.append(row)
    return sorted(rows, key=lambda row: (row["start"], row["track_index"], row["name"]))


def validate_relinked_prestate(timeline: Any) -> dict[str, Any]:
    rows = _target_candidates(timeline)
    errors = []
    if len(rows) != 5 or [(row["start"], row["end"]) for row in rows] != list(EXPECTED_SPANS):
        errors.append("carrier_cardinality_or_span")
    for row in rows:
        if row["track_index"] != EXPECTED_TRACK or row["duration"] != 4:
            errors.append(f"carrier_geometry:{row['start']}")
        if not row["item_uid"] or row["name"] != EXPECTED_MEDIA_NAME:
            errors.append(f"carrier_identity:{row['start']}")
        if row["media_uid"] != EXPECTED_MEDIA_UID or row["media_name"] != EXPECTED_MEDIA_NAME or not P4B.same_path(row["media_path"], EXPECTED_MEDIA_PATH):
            errors.append(f"carrier_media:{row['start']}")
        if row["fusion_comp_count"] != 0 or row["fusion_comp_names"]:
            errors.append(f"carrier_fusion:{row['start']}")
        if not all(callable(getattr(row["item"], method, None)) for method in ("AddFusionComp", "DeleteFusionCompByName", "GetFusionCompNameList")):
            errors.append(f"carrier_fusion_api:{row['start']}")
        if not any(callable(getattr(row["item"], method, None)) for method in ("SetName", "SetClipName", "SetProperty")):
            errors.append(f"carrier_name_api:{row['start']}")
    return {"ok": not errors, "classification": "RELINKED_ZERO_FUSION_PRESTATE" if not errors else "PRESTATE_MISMATCH",
            "errors": errors, "count": len(rows), "rows": [_public(row) for row in rows]}


def _load_prerequisite(root: Path, contract: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    relative = Path(str(contract.get("path") or ""))
    path = (root / relative).resolve()
    if root.resolve() not in path.parents or not path.is_file():
        raise ValueError("prerequisite_path")
    declared = str(contract.get("sha256") or "").upper()
    if declared != EXPECTED_PREREQUISITE_SHA256 or _sha256(path) != declared:
        raise ValueError("prerequisite_hash")
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    if report.get("ok") is not True or report.get("read_only") is not True or report.get("read_determinism_classification") != "TIMELINE_SIGNATURES_STABLE_TWO_PASS" or report.get("signature_mismatches"):
        raise ValueError("prerequisite_contract")
    inventory = [{"name": row.get("timeline_name"), "signature": (row.get("snapshot") or {}).get("signature")}
                 for row in (report.get("signature_pass_b") or {}).get("timelines", [])]
    expected = {row["name"]: row["signature"] for row in inventory}
    if len(inventory) != 29 or expected.get(TARGET_TIMELINE_NAME) != EXPECTED_PRESTATE_SIGNATURE or expected.get(HISTORICAL_TIMELINE_NAME) != EXPECTED_HISTORICAL_SIGNATURE or expected.get(REEL2_TIMELINE_NAME) != EXPECTED_REEL2_SIGNATURE:
        raise ValueError("prerequisite_inventory")
    return report, inventory


def _require_inventory(expected: Sequence[Mapping[str, Any]], actual: Sequence[Mapping[str, Any]]) -> None:
    key = lambda row: (row.get("name"), row.get("signature"))
    if Counter(map(key, expected)) != Counter(map(key, actual)):
        raise RuntimeError("live_inventory_drift")


def _media_and_references(project: Any, media_pool: Any, configured: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    media_rows, complete = PROBE.enumerate_media_pool(media_pool, [EXPECTED_MEDIA_NAME, "flash_neutral_rgba_v4"])
    if not complete or len(media_rows) != 1:
        raise RuntimeError("neutral_media_cardinality")
    media = media_rows[0]
    if media.get("folder_path") != "Master" or media.get("name") != EXPECTED_MEDIA_NAME or media.get("unique_id") != EXPECTED_MEDIA_UID or not P4B.same_path(str(media.get("resolved_path") or ""), EXPECTED_MEDIA_PATH) or abs(float(media.get("frame_rate") or 0) - 24.0) > 1e-6 or str(media.get("alpha_mode") or "").lower() != "straight":
        raise RuntimeError("neutral_media_identity")
    references = []
    for index in range(1, int(V1.safe_call(project, "GetTimelineCount", default=0) or 0) + 1):
        timeline = V1.safe_call(project, "GetTimelineByIndex", index, default=None)
        for track, item in V1.all_video_items(timeline):
            linked = V1.safe_call(item, "GetMediaPoolItem", default=None)
            if linked is not None and PROBE._media_row(linked).get("unique_id") == EXPECTED_MEDIA_UID:
                references.append({"timeline": P4B.timeline_name(timeline), **_public(_carrier_row(track, item))})
    target_fusion = 1 if configured else 0
    geometry = Counter((row["timeline"], row["track_index"], row["start"], row["end"], row["fusion_comp_count"]) for row in references)
    expected = Counter([(HISTORICAL_TIMELINE_NAME, 25, 426, 454, 0)] + [(TARGET_TIMELINE_NAME, EXPECTED_TRACK, start, end, target_fusion) for start, end in EXPECTED_SPANS])
    names_ok = all(
        row["name"] == (f"VC_FLASH_{EXPECTED_SPANS.index((row['start'], row['end'])) + 1:03d}_frame_{row['start'] + 2:04d}" if configured and row["timeline"] == TARGET_TIMELINE_NAME else EXPECTED_MEDIA_NAME)
        for row in references
    )
    if geometry != expected or not names_ok:
        raise RuntimeError("neutral_media_references")
    return media, sorted(references, key=lambda row: (row["timeline"], row["track_index"], row["start"]))


def _unaffected_signature(timeline: Any, carrier_uids: set[str]) -> str:
    rows = [P4B.item_snapshot(item, track) for track, item in V1.all_video_items(timeline) if V1.item_uid(item) not in carrier_uids]
    return V1.canonical_sha256(sorted(rows, key=lambda row: (row["track_index"], row["start"], row["end"], row["name"])))


def _rollback(timeline: Any, records: list[dict[str, Any]], expected_signature: str) -> dict[str, Any]:
    failures = []
    deleted = restored = 0
    for record in reversed(records):
        item = record["item"]
        current = _comp_names(item)
        new_names = record.get("new_comp_names") or [name for name in current if name not in record["comp_names_before"]]
        for name in reversed(new_names):
            if not V1.safe_call(item, "DeleteFusionCompByName", name, default=False):
                failures.append(f"delete_comp:{record['start']}:{name}")
            else:
                deleted += 1
        if V1.item_name(item) != record["name_before"]:
            rename = V1.set_item_name(item, record["name_before"])
            if not rename.get("ok"):
                failures.append(f"restore_name:{record['start']}")
            else:
                restored += 1
        if _comp_names(item) != record["comp_names_before"] or int(V1.safe_call(item, "GetFusionCompCount", default=0) or 0) != 0:
            failures.append(f"fusion_readback:{record['start']}")
    signature = P4B.timeline_snapshot(timeline).get("signature")
    if signature != expected_signature:
        failures.append("prestate_signature")
    return {"safe": not failures, "state": "relinked_zero_fusion_prestate" if not failures else "rollback_failed",
            "deleted_fusion_comp_count": deleted, "restored_name_count": restored, "signature": signature, "failures": failures}


def restore(resolve: Any, context: Mapping[str, Any]) -> dict[str, Any]:
    command = context.get("command") or {}
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    counters = {"media_imports": 0, "timeline_appends": 0, "timeline_item_deletes": 0, "media_pool_deletes": 0,
                "video_track_creates": 0, "fusion_configures": 0, "item_renames": 0, "project_saves": 0}
    report: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "mode": MODE, "run_id": run_id,
                              "classification": "FAILED_CLOSED", "mutation_counts": counters, "failures": []}
    project = previous_timeline = timeline = None
    selection_attempted = saved = False
    records: list[dict[str, Any]] = []
    mutated = False
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
        _, expected_inventory = _load_prerequisite(root, payload.get("prerequisite_report") or {})
        manager = V1.safe_call(resolve, "GetProjectManager", default=None)
        project = V1.safe_call(manager, "GetCurrentProject", default=None)
        if project is None or V1.safe_call(project, "GetName", default="") != PROJECT_NAME:
            raise RuntimeError("project_identity")
        previous_timeline = V1.safe_call(project, "GetCurrentTimeline", default=None)
        report["current_timeline_before"] = P4B.timeline_name(previous_timeline)
        timeline = BASE.find_one(project, TARGET_TIMELINE_NAME)
        live_inventory, non_target_before = BASE.non_target_inventory(project, TARGET_TIMELINE_NAME)
        _require_inventory(expected_inventory, live_inventory)
        pre_snapshot = P4B.timeline_snapshot(timeline)
        if pre_snapshot.get("signature") != EXPECTED_PRESTATE_SIGNATURE:
            raise RuntimeError("target_prestate_signature")
        prestate = validate_relinked_prestate(timeline)
        report["prestate"] = prestate
        if not prestate["ok"]:
            raise RuntimeError("relinked_prestate")
        media_pool = V1.safe_call(project, "GetMediaPool", default=None)
        media, references = _media_and_references(project, media_pool)
        report["neutral_media_before"] = media
        report["neutral_media_references_before"] = references
        rows = _target_candidates(timeline)
        carrier_uids = {row["item_uid"] for row in rows}
        unaffected_before = _unaffected_signature(timeline, carrier_uids)
        selection_attempted = True
        selected = bool(V1.safe_call(project, "SetCurrentTimeline", timeline, default=False))
        readback = P4B.timeline_name(V1.safe_call(project, "GetCurrentTimeline", default=None))
        report["current_timeline_selection"] = {"requested": TARGET_TIMELINE_NAME, "set_ok": selected, "readback": readback,
                                                "ok": selected and readback == TARGET_TIMELINE_NAME}
        if not selected or readback != TARGET_TIMELINE_NAME:
            raise RuntimeError("target_timeline_selection")
        for index, (spec, row) in enumerate(zip(flashes, rows), 1):
            item = row["item"]
            record = {"item": item, "item_uid": row["item_uid"], "start": row["start"], "name_before": row["name"],
                      "comp_names_before": list(row["fusion_comp_names"]), "new_comp_names": []}
            records.append(record)
            rename = V1.set_item_name(item, str(spec["name"]))
            if not rename.get("ok"):
                raise RuntimeError(f"carrier_rename:{index}")
            mutated = True
            counters["item_renames"] += 1
            configured = BASE.V1.configure_flash(item, spec, index)
            after_names = _comp_names(item)
            record["new_comp_names"] = [name for name in after_names if name not in record["comp_names_before"]]
            if not configured.get("ok") or len(record["new_comp_names"]) != 1 or int(V1.safe_call(item, "GetFusionCompCount", default=0) or 0) != 1:
                raise RuntimeError(f"fusion_configure:{index}")
            counters["fusion_configures"] += 1
        after_rows = _target_candidates(timeline)
        invariants = ("item_uid", "track_index", "start", "end", "duration", "media_uid", "media_name", "media_path")
        if len(after_rows) != 5 or any(any(before[key] != after[key] for key in invariants) for before, after in zip(rows, after_rows)):
            raise RuntimeError("carrier_invariants")
        flash = V4.neutral_flash_snapshot(timeline, flashes, EXPECTED_TRACK)
        if not flash.get("ok") or flash.get("neutral_carrier_count") != 5 or flash.get("source_video_carrier_count") != 0:
            raise RuntimeError("flash_readback")
        _, non_target_after = BASE.non_target_inventory(project, TARGET_TIMELINE_NAME)
        BASE.require_same_non_targets(non_target_before, non_target_after)
        unaffected_after = _unaffected_signature(timeline, carrier_uids)
        if unaffected_after != unaffected_before:
            raise RuntimeError("unaffected_target_changed")
        media_after, references_after = _media_and_references(project, media_pool, configured=True)
        if media_after != media or len(references_after) != 6:
            raise RuntimeError("shared_media_changed")
        if not V1.safe_call(manager, "SaveProject", default=False):
            raise RuntimeError("save_project")
        counters["project_saves"] = 1
        saved = True
        report.update({"ok": True, "classification": "RELINKED_INPLACE_FLASH_RESTORED", "save_project_count": 1, "duplicate_count": 0,
                       "flash_after": flash, "carrier_invariants_unchanged": True, "unaffected_target_signature_before": unaffected_before,
                       "unaffected_target_signature_after": unaffected_after, "non_target_timelines_unchanged": True,
                       "carriers_before": [_public(row) for row in rows], "carriers_after": [_public(row) for row in after_rows],
                       "neutral_media_after": media_after, "neutral_media_references_after": references_after,
                       "rollback": {"safe": True, "state": "restored_valid_state", "attempted": False}})
        return report
    except BaseException as exc:
        report["failures"] = [f"{type(exc).__name__}: {exc}"]
        report["traceback"] = traceback.format_exc()
        if mutated and not saved and timeline is not None:
            rollback = _rollback(timeline, records, EXPECTED_PRESTATE_SIGNATURE)
            rollback["attempted"] = True
            report["rollback"] = rollback
            if not rollback["safe"]:
                report["failures"].append("RuntimeError: rollback_failed")
        else:
            report["rollback"] = {"safe": True, "state": "unmutated_prestate", "attempted": False}
        return report
    finally:
        previous_name = P4B.timeline_name(previous_timeline)
        current_name = P4B.timeline_name(V1.safe_call(project, "GetCurrentTimeline", default=None))
        restore_needed = bool(selection_attempted and previous_timeline is not None and current_name != previous_name)
        restore_ok = True
        if restore_needed:
            restore_ok = bool(V1.safe_call(project, "SetCurrentTimeline", previous_timeline, default=False))
            restore_ok = restore_ok and P4B.timeline_name(V1.safe_call(project, "GetCurrentTimeline", default=None)) == previous_name
        report["previous_current_timeline_restoration"] = {"timeline": previous_name, "attempted": restore_needed, "ok": restore_ok}
        if not restore_ok:
            report["ok"] = False
            report["failures"].append("RuntimeError: previous_current_timeline_restore")


run = restore
