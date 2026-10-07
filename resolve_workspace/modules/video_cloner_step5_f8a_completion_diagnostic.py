"""Read-only F8A completion audit for raw Resolve track-state behavior."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import video_cloner_phase6_textplus_application as carrier
from resolve_workspace.modules import video_cloner_step5_f7_validation_rebuild as f7
from resolve_workspace.modules import video_cloner_step5_f8a_attribution_size_diagnostic as f8a

TASK_ID = "VIDEO_CLONER_STEP5_F8A_DIAGNOSTIC_COMPLETION_V1"
MODE = "step5_f8a_diagnostic_completion"


def _track_state(timeline: Any, track_type: str, index: int) -> dict[str, Any]:
    present = hasattr(timeline, "GetIsTrackEnabled")
    try:
        raw = timeline.GetIsTrackEnabled(track_type, index) if present else None
        return {"method_present": present, "raw_type": type(raw).__name__, "raw_repr": repr(raw), "reported_enabled": raw if isinstance(raw, bool) else None, "exception": None}
    except BaseException as exc:
        return {"method_present": present, "raw_type": None, "raw_repr": None, "reported_enabled": None, "exception": f7.IMPLEMENTATION.visual.base.compact_exception(exc)}


def _audit(timeline: Any, expected: Mapping[tuple[int, int, int], Mapping[str, Any]]) -> dict[str, Any]:
    tracks, items = [], []
    for track_type in ("video", "subtitle"):
        count = int(carrier._safe(timeline, "GetTrackCount", track_type, default=0) or 0)
        for index in range(1, count + 1):
            track = {"track_type": track_type, "track_index": index, "name": str(carrier._safe(timeline, "GetTrackName", track_type, index, default="") or ""), "api_reported_track_enabled_state": _track_state(timeline, track_type, index), "items": []}
            for item in list(carrier._safe(timeline, "GetItemListInTrack", track_type, index, default=[]) or []):
                start, end = int(carrier._safe(item, "GetStart", default=-1)), int(carrier._safe(item, "GetEnd", default=-1))
                fusion_count = int(carrier._safe(item, "GetFusionCompCount", default=0) or 0)
                contract_row = expected.get((index, start, end)) if track_type == "video" else None
                media = f8a._media(item)
                if track_type == "video" and index == 1:
                    classification = "SOURCE_BAKED_TEXT"
                elif contract_row is not None and fusion_count > 0:
                    classification = "TRACKED_F7_TEXTPLUS"
                elif track_type == "subtitle" or carrier._title_text(item) is not None or fusion_count > 0:
                    classification = "OTHER_RESOLVE_TEXT_LAYER"
                else:
                    classification = "UNKNOWN"
                row = {
                    "track_type": track_type,
                    "track_index": index,
                    "item_name": str(carrier._safe(item, "GetName", default="") or ""),
                    "item_type": media.get("Type") or ("TextPlus" if fusion_count else "Unknown"),
                    "start": start,
                    "end": end,
                    "fusion_comp_count": fusion_count,
                    "source_identity": None if contract_row is None else contract_row["source_identity"],
                    "styled_text": carrier._title_text(item),
                    "media_path": media.get("File Path") or media.get("FilePath") or media.get("Path"),
                    "classification": classification,
                }
                track["items"].append(row)
                items.append(row)
            tracks.append(track)
    cases = []
    for case, frame, source_frame, identities in f8a.CASES:
        active = []
        for item in items:
            row = dict(item)
            row["active_at_case_frame"] = item["start"] <= frame < item["end"]
            if row["active_at_case_frame"] and row["classification"] != "UNKNOWN":
                active.append(row)
        cases.append({"case": case, "timeline_frame": frame, "source_frame": source_frame, "expected_identities": list(identities), "active_text_capable_items": active})
    states = [track["api_reported_track_enabled_state"] for track in tracks]
    contradiction = bool(states) and all(state["reported_enabled"] is False for state in states)
    return {
        "tracks": tracks,
        "cases": cases,
        "video_track_count": sum(track["track_type"] == "video" for track in tracks),
        "subtitle_track_count": sum(track["track_type"] == "subtitle" for track in tracks),
        "inventory_filtered_by_enabled_state": False,
        "other_resolve_text_layer_count": sum(item["classification"] == "OTHER_RESOLVE_TEXT_LAYER" for item in items),
        "unknown_count": sum(item["classification"] == "UNKNOWN" for item in items),
        "api_state_contradicts_prior_rendered_output": contradiction,
        "api_track_enabled_interpretation": "UNRELIABLE_FOR_VISIBILITY_ATTRIBUTION" if contradiction else "REVIEW_RAW_RESULTS",
    }


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    command = context.get("command") or {}
    payload = command.get("payload") or {}
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "run_id": run_id, "classification": "BLOCKED"}
    project = None
    before_inventory: list[dict[str, str]] = []
    before_target: dict[str, Any] = {}
    report_dir = Path(str(payload.get("report_dir") or ROOT / ".agent/reports" / TASK_ID / run_id)).resolve()
    try:
        if command.get("task_id") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id:
            raise ValueError("command_identity")
        manager = carrier._safe(resolve, "GetProjectManager")
        project = carrier._safe(manager, "GetCurrentProject")
        if project is None or carrier._safe(project, "GetName", default="") != f8a.PROJECT:
            raise ValueError("project_identity")
        matches = [row for row in carrier._timelines(project) if carrier._safe(row, "GetName", default="") == f8a.TARGET]
        if len(matches) != 1 or carrier._unique_id(matches[0]) != f8a.TARGET_UID:
            raise ValueError("target_identity")
        target = matches[0]
        before_inventory = f8a._inventory(project)
        before_target = carrier.timeline_snapshot(target)
        contract_path = Path(str(payload["contract_path"])).resolve()
        if f7.IMPLEMENTATION.base.sha(contract_path) != payload.get("contract_sha256"):
            raise ValueError("contract_hash")
        contract = f7.IMPLEMENTATION.base.read(contract_path)
        expected = {(int(row["z_order_track"]["resolve_track"]), *row["resolve_interval"]): row for row in contract["objects"]}
        audit = _audit(target, expected)
        f7.IMPLEMENTATION.base.write(report_dir / "resolve_layer_audit_completion.json", audit)
        result.update({"ok": True, "classification": "F8A_LAYER_AUDIT_COMPLETED", "layer_audit": str(report_dir / "resolve_layer_audit_completion.json")})
    except BaseException as exc:
        result["error"] = f7.IMPLEMENTATION.visual.base.compact_exception(exc)
    finally:
        cleanup = {"project_saved": False}
        if project is not None:
            cleanup["inventory_unchanged"] = f8a._inventory(project) == before_inventory
            target = next((row for row in carrier._timelines(project) if carrier._unique_id(row) == f8a.TARGET_UID), None)
            cleanup["target_unchanged"] = target is not None and carrier.timeline_snapshot(target) == before_target
        cleanup["ok"] = cleanup.get("inventory_unchanged") is True and cleanup.get("target_unchanged") is True and cleanup["project_saved"] is False
        result["cleanup"] = cleanup
        if not cleanup["ok"]:
            result.update({"ok": False, "classification": "BLOCKED"})
        f7.IMPLEMENTATION.base.write(report_dir / "f8a_completion_diagnostic.json", result)
    return result
