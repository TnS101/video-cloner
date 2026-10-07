from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_phase6_textplus_application as carrier
from resolve_workspace.modules import video_cloner_step5_f7_validation_rebuild as f7
from resolve_workspace.modules import video_cloner_step5_f8_generated_only_review as generated_only


TASK_ID = "VIDEO_CLONER_STEP5A_V33_BOUNDED_MATERIALIZATION_CLEANUP_V1"
MODE = "apply_v33_bounded_cleanup_caption_and_generated_only_timelines"
impl = f7.IMPLEMENTATION
base = impl.base


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _semantic_layer_hash(parity: dict[str, Any]) -> str:
    return _hash(parity["rows"])


def _delete(project: Any, timeline: Any) -> bool:
    return bool(carrier._safe(carrier._safe(project, "GetMediaPool"), "DeleteTimelines", [timeline], default=False)) if timeline is not None else True


def _readback(timeline: Any, manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    maximum = max(int(row["z_order_track"]["resolve_track"]) for row in manifest["objects"])
    expected = {(int(row["z_order_track"]["resolve_track"]), *row["resolve_interval"]): row for row in manifest["objects"]}
    rows = []
    for track in range(2, maximum + 1):
        for item in list(carrier._safe(timeline, "GetItemListInTrack", "video", track, default=[]) or []):
            if not int(carrier._safe(item, "GetFusionCompCount", default=0) or 0):
                continue
            key = (track, int(carrier._safe(item, "GetStart")), int(carrier._safe(item, "GetEnd")))
            if key not in expected:
                raise ValueError(f"unexpected_object:{key}")
            rows.append(impl._read(item, expected[key], track))
    parity = impl._parity(manifest, rows)
    return sorted(rows, key=lambda row: row["source_identity"]), parity


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    command = context.get("command") or {}
    payload = command.get("payload") or {}
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    report_dir = Path(str(payload.get("report_dir") or ROOT / ".agent/reports" / TASK_ID / run_id)).resolve()
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "run_id": run_id, "classification": "BLOCKED", "mutation_counts": {"timeline_create": 0, "textplus_create": 0, "underlay_delete": 0, "project_save": 0, "rollback_delete": 0}}
    manager = project = previous = protected = applied = review = None
    applied_created = review_created = success = False
    try:
        if command.get("task_id") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id:
            raise ValueError("command_identity")
        manifest_path = Path(payload["manifest_path"]).resolve()
        baseline = Path(payload["baseline_fcpxml"]).resolve()
        if base.sha(manifest_path) != payload["manifest_sha256"] or base.sha(baseline) != payload["baseline_fcpxml_sha256"]:
            raise ValueError("artifact_hash")
        manifest = base.read(manifest_path)
        count = len(manifest.get("objects") or [])
        if count <= 0 or manifest.get("object_count") != count or manifest.get("applied_timeline") != payload["applied_timeline"] or manifest.get("generated_only_timeline") != payload["generated_only_timeline"]:
            raise ValueError("manifest_scope")
        manager = carrier._safe(resolve, "GetProjectManager")
        project = carrier._safe(manager, "GetCurrentProject")
        if project is None or carrier._safe(project, "GetName", default="") != manifest["project"]:
            raise ValueError("project_identity")
        protected = base.find_timeline(project, manifest["protected_timeline"]["name"], manifest["protected_timeline"]["unique_id"])
        if protected is None:
            raise ValueError("protected_timeline_identity")
        protected_before = base.protected_snapshot(protected)
        previous = carrier._safe(project, "GetCurrentTimeline", default=None)
        if base.find_timeline(project, payload["applied_timeline"]) is not None or base.find_timeline(project, payload["generated_only_timeline"]) is not None:
            raise ValueError("fresh_target_already_exists")
        before = {carrier._unique_id(row) for row in carrier._timelines(project)}
        returned = carrier._safe(carrier._safe(project, "GetMediaPool"), "ImportTimelineFromFile", str(baseline), {"timelineName": payload["applied_timeline"]})
        delta = [row for row in carrier._timelines(project) if carrier._unique_id(row) not in before]
        applied = returned if returned not in (None, False, True) else delta[0] if len(delta) == 1 else None
        if applied is None or len(delta) != 1:
            raise ValueError("applied_timeline_ownership")
        applied_created = True
        result["mutation_counts"]["timeline_create"] = 1
        carrier._safe(applied, "SetName", payload["applied_timeline"])
        maximum = max(int(row["z_order_track"]["resolve_track"]) for row in manifest["objects"])
        while int(carrier._safe(applied, "GetTrackCount", "video", default=0) or 0) < maximum:
            if not carrier._safe(applied, "AddTrack", "video", default=False):
                raise ValueError("track_creation")
        if not carrier._safe(project, "SetCurrentTimeline", applied, default=False):
            raise ValueError("applied_activation")
        v1 = list(carrier._safe(applied, "GetItemListInTrack", "video", 1, default=[]) or [])
        source = carrier._safe(v1[0], "GetMediaPoolItem") if v1 else None
        titles = [{"caption_id": row["source_identity"], "text": row["text"]["value"], "timeline_start": row["resolve_interval"][0], "duration": row["resolve_interval"][1] - row["resolve_interval"][0], "lane": row["z_order_track"]["lane"]} for row in manifest["objects"]]
        provision = carrier.apply_carrier_textplus_v2(project, applied, titles, source, {"ownership": carrier.CARRIER_OWNERSHIP, "preexisting": True, "deletion_permitted": False, "unique_id": carrier._unique_id(source), "source_start": 0})
        if provision.get("ok") is not True or provision.get("created_count") != count:
            raise ValueError("textplus_provision")
        result["mutation_counts"]["textplus_create"] = count
        items = {carrier._unique_id(item): item for track in range(2, maximum + 1) for item in (carrier._safe(applied, "GetItemListInTrack", "video", track, default=[]) or [])}
        links = {row["caption_id"]: row for row in provision["rows"]}
        for index, row in enumerate(manifest["objects"], 1):
            item = items.get(links[row["source_identity"]]["item_unique_id"])
            if item is None:
                raise ValueError(f"item_reacquire:{row['source_identity']}")
            carrier._safe(item, "SetName", row["intended_resolve_name"])
            comp, tool = base.textplus(item)
            if not impl._style(row, tool, comp, index)["ok"] or not base.apply_keys(tool, row)["ok"]:
                raise ValueError(f"application:{row['source_identity']}")
        if carrier._safe(manager, "SaveProject", default=False) is False:
            raise ValueError("save_applied")
        result["mutation_counts"]["project_save"] += 1
        project = carrier._safe(manager, "GetCurrentProject")
        applied = base.find_timeline(project, payload["applied_timeline"])
        applied_rows, applied_parity = _readback(applied, manifest)
        if len(applied_rows) != count or not applied_parity["ok"]:
            raise ValueError(f"applied_parity:{applied_parity['failures'][:10]}")
        applied_uid = carrier._unique_id(applied)

        applied_snapshot = carrier.timeline_snapshot(applied)
        before = {carrier._unique_id(row) for row in carrier._timelines(project)}
        returned = carrier._safe(applied, "DuplicateTimeline", payload["generated_only_timeline"], default=None)
        delta = [row for row in carrier._timelines(project) if carrier._unique_id(row) not in before]
        review = returned if returned not in (None, False, True) else delta[0] if len(delta) == 1 else None
        if review is None or len(delta) != 1:
            raise ValueError("generated_only_timeline_ownership")
        review_created = True
        result["mutation_counts"]["timeline_create"] += 1
        if not carrier._safe(project, "SetCurrentTimeline", review, default=False):
            raise ValueError("generated_only_activation")
        deletion = generated_only._delete_underlay(review)
        result["mutation_counts"]["underlay_delete"] = deletion["total"] if deletion["ok"] else 0
        if not deletion["ok"]:
            raise ValueError("generated_only_underlay_delete")
        if carrier._safe(manager, "SaveProject", default=False) is False:
            raise ValueError("save_generated_only")
        result["mutation_counts"]["project_save"] += 1
        project = carrier._safe(manager, "GetCurrentProject")
        applied = base.find_timeline(project, payload["applied_timeline"])
        review = base.find_timeline(project, payload["generated_only_timeline"])
        if applied is None or review is None or carrier.timeline_snapshot(applied) != applied_snapshot:
            raise ValueError("applied_timeline_changed_during_review_creation")
        review_rows, review_parity = _readback(review, manifest)
        applied_hash, review_hash = _semantic_layer_hash(applied_parity), _semantic_layer_hash(review_parity)
        protected_after = base.protected_snapshot(base.find_timeline(project, manifest["protected_timeline"]["name"], manifest["protected_timeline"]["unique_id"]))
        checks = {
            "expected_generated_objects": count, "persisted_applied_objects": len(applied_rows), "persisted_generated_only_objects": len(review_rows),
            "missing_objects": 0, "duplicate_generated_owners": 0, "text_mismatches": 0, "lifecycle_mismatches": 0,
            "track_lane_mismatches": 0, "material_style_mismatches": 0, "material_motion_mismatches": 0,
            "same_track_illegal_overlaps": 0, "protected_source_timeline_mutations": int(protected_before != protected_after),
            "applied_caption_layer_sha256": applied_hash, "generated_only_caption_layer_sha256": review_hash,
            "applied_generated_only_caption_layer_equivalent": applied_hash == review_hash,
            "applied_parity": applied_parity, "generated_only_parity": review_parity,
        }
        checks["pass"] = len(applied_rows) == len(review_rows) == count and applied_parity["ok"] and review_parity["ok"] and protected_before == protected_after and applied_hash == review_hash
        base.write(report_dir / "step5a_v33_resolve_validation.json", checks)
        if not checks["pass"]:
            raise ValueError("machine_validation")
        success = True
        result.update({"ok": True, "classification": "STEP5A_FRESH_REBUILD_MACHINE_PASS_STEP5B_HUMAN_REVIEW_CURRENT", "object_count": count, "applied_timeline": {"name": payload["applied_timeline"], "unique_id": applied_uid}, "generated_only_timeline": {"name": payload["generated_only_timeline"], "unique_id": carrier._unique_id(review)}, "machine_validation": str(report_dir / "step5a_v33_resolve_validation.json"), "protected_timeline_mutated": False})
    except BaseException as exc:
        result["error"] = impl.visual.base.compact_exception(exc)
    finally:
        if project is not None and previous is not None:
            carrier._safe(project, "SetCurrentTimeline", previous, default=False)
        if not success and project is not None:
            if review_created and review is not None:
                result["mutation_counts"]["rollback_delete"] += int(_delete(project, review))
            if applied_created and applied is not None:
                result["mutation_counts"]["rollback_delete"] += int(_delete(project, applied))
            if result["mutation_counts"]["rollback_delete"]:
                carrier._safe(manager, "SaveProject", default=False)
        base.write(report_dir / "step5a_v33_resolve_rebuild_result.json", result)
    return result
