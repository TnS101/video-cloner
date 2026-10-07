"""Apply a fresh F9 canonical-ownership contract with the accepted F7 adapter."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_step5_f7_validation_rebuild as f7

TASK_ID = "VIDEO_CLONER_STEP5_F9_CANONICAL_DISPLAY_OWNERSHIP_REBUILD_V1"
MODE = "apply_fresh_canonical_validation_rebuild"

impl = f7.IMPLEMENTATION
base = impl.base
carrier = impl.carrier


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    command = context.get("command") or {}
    payload = command.get("payload") or {}
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {
        "ok": False,
        "task_id": TASK_ID,
        "run_id": run_id,
        "failures": [],
        "mutation_counts": {"timeline_create": 0, "textplus_create": 0, "project_save": 0, "rollback_delete": 0},
    }
    target = project = previous = None
    created = False
    try:
        if command.get("task_id") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id:
            raise ValueError("command_identity")
        contract_path = Path(payload["contract_path"]).resolve()
        audit_path = Path(payload["ownership_audit_path"]).resolve()
        baseline = Path(payload["baseline_fcpxml"]).resolve()
        report_dir = Path(payload["report_dir"]).resolve()
        if base.sha(contract_path) != payload["contract_sha256"] or base.sha(audit_path) != payload["ownership_audit_sha256"] or base.sha(baseline) != payload["baseline_fcpxml_sha256"]:
            raise ValueError("artifact_hash")
        contract = base.read(contract_path)
        audit = base.read(audit_path)
        count = len(contract.get("objects") or [])
        if count <= 0 or contract.get("object_count") != count or contract.get("validation_timeline") != payload["target_timeline"]:
            raise ValueError("compile_contract")
        if audit.get("final_renderable_object_count") != count or audit.get("ownership_conflicts") or audit.get("source_required_missing_objects") or audit.get("unsupported_duplicate_owners"):
            raise ValueError("ownership_audit")

        manager = carrier._safe(resolve, "GetProjectManager")
        project = carrier._safe(manager, "GetCurrentProject")
        if project is None or carrier._safe(project, "GetName", default="") != contract["project"]:
            raise ValueError("project_identity")
        protected = base.find_timeline(project, contract["protected_timeline"]["name"], contract["protected_timeline"]["unique_id"])
        if protected is None:
            raise ValueError("protected_timeline_identity")
        protected_before = base.protected_snapshot(protected)
        previous = carrier._safe(project, "GetCurrentTimeline")
        if base.find_timeline(project, contract["validation_timeline"]) is not None:
            raise ValueError("fresh_target_already_exists")

        before_ids = {carrier._unique_id(row) for row in carrier._timelines(project)}
        returned = carrier._safe(carrier._safe(project, "GetMediaPool"), "ImportTimelineFromFile", str(baseline), {"timelineName": contract["validation_timeline"]})
        delta = [row for row in carrier._timelines(project) if carrier._unique_id(row) not in before_ids]
        target = returned if returned not in (None, False, True) else delta[0] if len(delta) == 1 else None
        if target is None or len(delta) != 1:
            raise ValueError("target_ownership")
        created = True
        result["mutation_counts"]["timeline_create"] = 1
        carrier._safe(target, "SetName", contract["validation_timeline"])
        if carrier._safe(target, "GetName", default="") != contract["validation_timeline"]:
            raise ValueError("target_name")

        max_track = max(int(row["z_order_track"]["resolve_track"]) for row in contract["objects"])
        while int(carrier._safe(target, "GetTrackCount", "video", default=0) or 0) < max_track:
            if not carrier._safe(target, "AddTrack", "video", default=False):
                raise ValueError("track_creation")
        if not carrier._safe(project, "SetCurrentTimeline", target, default=False):
            raise ValueError("target_activation")
        v1 = list(carrier._safe(target, "GetItemListInTrack", "video", 1, default=[]) or [])
        source = carrier._safe(v1[0], "GetMediaPoolItem") if v1 else None
        titles = [{"caption_id": row["source_identity"], "text": row["text"]["value"], "timeline_start": row["resolve_interval"][0], "duration": row["resolve_interval"][1] - row["resolve_interval"][0], "lane": row["z_order_track"]["lane"]} for row in contract["objects"]]
        provision = carrier.apply_carrier_textplus_v2(project, target, titles, source, {"ownership": carrier.CARRIER_OWNERSHIP, "preexisting": True, "deletion_permitted": False, "unique_id": carrier._unique_id(source), "source_start": 0})
        if provision.get("ok") is not True or provision.get("created_count") != count:
            raise ValueError("textplus_provision")
        result["mutation_counts"]["textplus_create"] = count

        items = {carrier._unique_id(item): item for track in range(2, max_track + 1) for item in (carrier._safe(target, "GetItemListInTrack", "video", track, default=[]) or [])}
        links = {row["caption_id"]: row for row in provision["rows"]}
        applied = []
        for index, row in enumerate(contract["objects"], 1):
            item = items.get(links[row["source_identity"]]["item_unique_id"])
            if item is None:
                raise ValueError(f"item_reacquire:{row['source_identity']}")
            carrier._safe(item, "SetName", row["intended_resolve_name"])
            comp, tool = base.textplus(item)
            style = impl._style(row, tool, comp, index)
            keys = base.apply_keys(tool, row)
            if not style["ok"] or not keys["ok"]:
                raise ValueError(f"application:{row['source_identity']}")
            applied.append({"source_identity": row["source_identity"], "item_unique_id": carrier._unique_id(item), "track": row["z_order_track"]["resolve_track"], "style": style, "keyframes": keys})

        if carrier._safe(manager, "SaveProject", default=False) is False:
            raise ValueError("save_project")
        result["mutation_counts"]["project_save"] = 1
        project = carrier._safe(manager, "GetCurrentProject")
        target = base.find_timeline(project, contract["validation_timeline"])
        actual_items = [(track, item) for track in range(2, max_track + 1) for item in (carrier._safe(target, "GetItemListInTrack", "video", track, default=[]) or []) if carrier._safe(item, "GetFusionCompCount", default=0)]
        if len(actual_items) != count:
            raise ValueError(f"object_count:{len(actual_items)}")
        expected = {(row["z_order_track"]["resolve_track"], *row["resolve_interval"]): row for row in contract["objects"]}
        readback = []
        for track, item in actual_items:
            key = (track, int(carrier._safe(item, "GetStart")), int(carrier._safe(item, "GetEnd")))
            if key not in expected:
                raise ValueError(f"unexpected_object:{key}")
            readback.append(impl._read(item, expected[key], track))
        parity = impl._parity(contract, readback)
        if not parity["ok"]:
            raise ValueError(f"parity:{parity['failures'][:10]}")
        protected_after = base.protected_snapshot(base.find_timeline(project, contract["protected_timeline"]["name"], contract["protected_timeline"]["unique_id"]))
        if protected_before != protected_after:
            raise ValueError("protected_timeline_mutated")
        target_snap = carrier.timeline_snapshot(target)
        base.write(report_dir / "step5_f9_canonical_application.json", {"schema": "video_cloner_step5_f9_canonical_application", "objects": applied, "object_count": count, "timeline": target_snap})
        base.write(report_dir / "step5_f9_canonical_readback.json", {"schema": "video_cloner_step5_f9_canonical_readback", "objects": sorted(readback, key=lambda row: row["source_identity"]), "object_count": count, "timeline": target_snap})
        base.write(report_dir / "step5_f9_canonical_validation.json", {"schema": "video_cloner_step5_f9_canonical_validation", "expected_renderable_objects": count, "persisted_renderable_objects": len(readback), "missing_objects": 0, "unexpected_extra_objects": 0, "text_mismatches": 0, "lifecycle_mismatches": 0, "style_mismatches": 0, "placement_mismatches": 0, "scale_mismatches": 0, "ownership_conflicts": 0, "unsupported_fragment_renders": 0, "duplicate_canonical_owners": 0, "protected_timeline_mutated": False, "project_save_succeeded": True, "parity": parity, "pass": True})
        result.update({"ok": True, "classification": "PASS_F7_CANONICAL_RESOLVE_REBUILD", "object_count": count, "validation_timeline": {"name": target_snap["name"], "unique_id": target_snap["unique_id"]}, "protected_timeline_mutated": False})
    except Exception as exc:
        result["failures"] = [f"{type(exc).__name__}: {exc}"]
        if created and project is not None and target is not None:
            deleted = bool(carrier._safe(carrier._safe(project, "GetMediaPool"), "DeleteTimelines", [target], default=False))
            result["mutation_counts"]["rollback_delete"] = int(deleted)
            if deleted:
                carrier._safe(manager, "SaveProject", default=False)
    finally:
        if project is not None and previous is not None:
            carrier._safe(project, "SetCurrentTimeline", previous, default=False)
    return result
