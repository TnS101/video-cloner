"""Read-only full machine validation of the existing persisted F7 timeline."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_phase6_textplus_application as carrier
from resolve_workspace.modules import video_cloner_step5_f7_validation_rebuild as f7

TASK_ID = "VIDEO_CLONER_STEP5_F7_READONLY_MACHINE_VALIDATION_V1"
MODE = "validate_persisted_f7_readonly"
SOURCE_RUN_ID = "20261002T093228130622Z_8a43be1aa99a4e2fa6ec66203b559cbd"
TARGET_TIMELINE = "VIDEO_CLONER_STEP5A_TEXTPLUS_VALIDATION_F7_66203b559cbd"


def _placement(contract: Mapping[str, Any]) -> dict[str, Any]:
    objects = list(contract.get("objects") or [])
    mismatches = [
        row["source_identity"] for row in objects
        if row["z_order_track"].get("lane") is None
        or int(row["z_order_track"]["lane"]) != int(row["z_order_track"]["resolve_track"]) - 1
    ]
    overlaps = []
    for track in sorted({int(row["z_order_track"]["resolve_track"]) for row in objects}):
        rows = sorted(
            (row for row in objects if int(row["z_order_track"]["resolve_track"]) == track),
            key=lambda row: (row["resolve_interval"][0], row["resolve_interval"][1], row["source_identity"]),
        )
        for index, left in enumerate(rows):
            for right in rows[index + 1:]:
                if right["resolve_interval"][0] >= left["resolve_interval"][1]:
                    break
                overlaps.append({"track": track, "left": left["source_identity"], "right": right["source_identity"]})
    return {
        "object_count": len(objects),
        "missing_lane_count": sum(row["z_order_track"].get("lane") is None for row in objects),
        "lane_track_mismatch_count": len(mismatches),
        "lane_track_mismatches": mismatches,
        "same_track_overlap_count": len(overlaps),
        "same_track_overlaps": overlaps,
        "pass": len(objects) == 65 and not mismatches and not overlaps,
    }


def _failure_count(failures: list[str], names: set[str]) -> int:
    return sum(value.rsplit(":", 1)[-1] in names for value in failures)


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    command = context.get("command") or {}
    payload = command.get("payload") or {}
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {
        "ok": False,
        "task_id": TASK_ID,
        "run_id": run_id,
        "classification": "BLOCKED",
        "failures": [],
        "mutation_counts": {"timeline_create": 0, "textplus_create": 0, "project_save": 0, "delete": 0},
    }
    try:
        if command.get("task_id") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id:
            raise ValueError("command_identity")
        if payload.get("source_run_id") != SOURCE_RUN_ID or payload.get("target_timeline") != TARGET_TIMELINE or payload.get("read_only") is not True:
            raise ValueError("validation_scope")
        contract_path = Path(str(payload["contract_path"])).resolve()
        source_report_path = Path(str(payload["source_bridge_report_path"])).resolve()
        report_dir = Path(str(payload["report_dir"])).resolve()
        if f7.IMPLEMENTATION.base.sha(contract_path) != payload.get("contract_sha256") or f7.IMPLEMENTATION.base.sha(source_report_path) != payload.get("source_bridge_report_sha256"):
            raise ValueError("artifact_hash")
        contract = f7.IMPLEMENTATION.base.read(contract_path)
        source_report = f7.IMPLEMENTATION.base.read(source_report_path)
        persistence = {
            "source_run_id": SOURCE_RUN_ID,
            "source_bridge_report_path": str(source_report_path),
            "source_bridge_report_sha256": payload["source_bridge_report_sha256"],
            "timeline_create": source_report.get("mutation_counts", {}).get("timeline_create"),
            "textplus_create": source_report.get("mutation_counts", {}).get("textplus_create"),
            "project_save": source_report.get("mutation_counts", {}).get("project_save"),
            "delete": source_report.get("mutation_counts", {}).get("delete"),
        }
        if (
            source_report.get("run_id") != SOURCE_RUN_ID
            or persistence["timeline_create"] != 1
            or persistence["textplus_create"] != 65
            or persistence["project_save"] != 1
            or persistence["delete"] != 0
        ):
            raise ValueError("persistence_evidence")
        if contract.get("object_count") != 65 or contract.get("validation_timeline") != TARGET_TIMELINE:
            raise ValueError("compile_contract")
        placement = _placement(contract)
        target_6000 = next(row for row in contract["objects"] if row["source_identity"] == "caption_tracklet_0089")
        if target_6000["resolve_interval"] != [542, 596] or len(target_6000["keyframes"]["scale"]) != 9:
            raise ValueError("f6_6000_authority")

        manager = carrier._safe(resolve, "GetProjectManager")
        project = carrier._safe(manager, "GetCurrentProject")
        if project is None or carrier._safe(project, "GetName", default="") != contract["project"]:
            raise ValueError("project_identity")
        protected = f7.IMPLEMENTATION.base.find_timeline(project, contract["protected_timeline"]["name"], contract["protected_timeline"]["unique_id"])
        target = f7.IMPLEMENTATION.base.find_timeline(project, TARGET_TIMELINE)
        if protected is None or target is None:
            raise ValueError("timeline_identity")
        protected_before = f7.IMPLEMENTATION.base.protected_snapshot(protected)

        expected = {
            (int(row["z_order_track"]["resolve_track"]), *row["resolve_interval"]): row
            for row in contract["objects"]
        }
        max_track = max(key[0] for key in expected)
        actual_items = [
            (track, item)
            for track in range(2, max_track + 1)
            for item in (carrier._safe(target, "GetItemListInTrack", "video", track, default=[]) or [])
            if carrier._safe(item, "GetFusionCompCount", default=0)
        ]
        seen: set[tuple[int, int, int]] = set()
        unexpected = []
        readback = []
        for track, item in actual_items:
            key = (track, int(carrier._safe(item, "GetStart")), int(carrier._safe(item, "GetEnd")))
            row = expected.get(key)
            if row is None or key in seen:
                unexpected.append({"track": track, "start": key[1], "end": key[2], "item_unique_id": carrier._unique_id(item)})
                continue
            seen.add(key)
            readback.append(f7.IMPLEMENTATION._read(item, row, track))
        missing = [row["source_identity"] for key, row in expected.items() if key not in seen]
        parity = f7.IMPLEMENTATION._parity(contract, readback)
        protected_after = f7.IMPLEMENTATION.base.protected_snapshot(protected)
        protected_unchanged = protected_before == protected_after
        failures = list(parity["failures"])
        style_names = {"font", "font_style", "size", "position", "fill", "stroke", "opacity_visibility", "shadow", "static_rotation", "keyframes", "opacity", "italic_treatment", "gradient"}
        validation = {
            "schema": "video_cloner_step5_f7_readonly_machine_validation_v1",
            "task_id": TASK_ID,
            "run_id": run_id,
            "source_failed_run_id": SOURCE_RUN_ID,
            "target_timeline": {"name": TARGET_TIMELINE, "unique_id": carrier._unique_id(target), "exists": True},
            "read_only": True,
            "expected_renderable_objects": 65,
            "persisted_renderable_objects": len(actual_items),
            "missing_objects": missing,
            "missing_object_count": len(missing),
            "unexpected_extras": unexpected,
            "unexpected_extra_count": len(unexpected),
            "text_mismatches": _failure_count(failures, {"text"}),
            "lifecycle_mismatches": _failure_count(failures, {"timing"}),
            "style_projection_mismatches": _failure_count(failures, style_names),
            "placement_mismatches": _failure_count(failures, {"z_order"}),
            "parity": parity,
            "placement": placement,
            "f6_6000_interval": target_6000["resolve_interval"],
            "f6_6000_scale_key_count": len(target_6000["keyframes"]["scale"]),
            "protected_timeline": {"before": protected_before, "after": protected_after, "unchanged": protected_unchanged},
            "original_full_run_persistence": persistence,
        }
        validation["pass"] = bool(
            len(actual_items) == 65
            and not missing
            and not unexpected
            and parity["ok"] is True
            and placement["pass"] is True
            and protected_unchanged
        )
        f7.IMPLEMENTATION.base.write(report_dir / "step5_f7_readonly_readback.json", {
            "schema": "video_cloner_step5_f7_readonly_readback_v1",
            "object_count": len(readback),
            "objects": sorted(readback, key=lambda row: row["source_identity"]),
        })
        f7.IMPLEMENTATION.base.write(report_dir / "step5_f7_validation.json", validation)
        f7.IMPLEMENTATION.base.write(report_dir / "step5_f7_machine_pass.json", {
            "schema": "video_cloner_step5_f7_machine_pass_v1",
            "task_id": TASK_ID,
            "run_id": run_id,
            "target_timeline": TARGET_TIMELINE,
            "classification": "F7_MACHINE_PASS" if validation["pass"] else "BLOCKED",
            "pass": validation["pass"],
            "validation_path": str(report_dir / "step5_f7_validation.json"),
        })
        if not validation["pass"]:
            raise ValueError("f7_machine_validation")
        result.update({
            "ok": True,
            "classification": "F7_MACHINE_PASS",
            "validation_path": str(report_dir / "step5_f7_validation.json"),
            "machine_pass_path": str(report_dir / "step5_f7_machine_pass.json"),
            "object_count": 65,
            "protected_timeline_mutated": False,
        })
    except BaseException as exc:
        result["failures"] = [f7.IMPLEMENTATION.visual.base.compact_exception(exc)]
    return result

