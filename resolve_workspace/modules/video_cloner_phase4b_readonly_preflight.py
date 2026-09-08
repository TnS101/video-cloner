"""Read-only Resolve preflight for the Reel #2 Phase 4B timeline."""
from __future__ import annotations

from collections import Counter
import importlib.util
from pathlib import Path
import re
from typing import Any

_spec = importlib.util.spec_from_file_location("vc_phase4b_for_readonly_preflight", Path(__file__).with_name("video_cloner_phase4b_timeline_application.py"))
if _spec is None or _spec.loader is None:
    raise ImportError("cannot_load_phase4b")
_phase4b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_phase4b)
find_timelines = _phase4b.find_timelines
parse_fcpxml_contract = _phase4b.parse_fcpxml_contract
project_timelines = _phase4b.project_timelines
safe = _phase4b.safe
sha256 = _phase4b.sha256
timeline_inventory = _phase4b.timeline_inventory
timeline_name = _phase4b.timeline_name
validate_target = _phase4b.validate_target

TASK_ID = "VIDEO_CLONER_PHASE4B_READONLY_PREFLIGHT_V1"
MODE = "phase4b_readonly_preflight"
ACTION = "inspect_phase4b_readiness"


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    report: dict[str, Any] = {
        "ok": True,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "action": ACTION,
        "operation_id": None,
        "resolve_connected": resolve is not None,
        "project_name": None,
        "current_timeline_name": None,
        "media_pool_available": False,
        "timeline_count": 0,
        "timeline_names": [],
        "duplicate_name_counts": {},
        "target_timeline_name": None,
        "target_occurrence_count": 0,
        "non_target_timeline_inventory": [],
        "target_validation": None,
        "readiness": None,
        "read_only": True,
        "timeline_modified": False,
        "mutation_counts": {"imports": 0, "selections": 0, "creates": 0, "deletes": 0, "renames": 0, "media_imports": 0, "saves": 0},
        "failures": [],
    }
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        if command.get("task") != TASK_ID or command.get("run_id") != run_id or command.get("mode") != MODE or payload.get("action") != ACTION:
            raise ValueError("command_identity")
        if payload.get("read_only") is not True or payload.get("mutation_permitted") is not False:
            raise ValueError("read_only_authority")
        report["operation_id"] = payload.get("operation_id")
        artifact = Path(str(payload.get("fcpxml_path") or "")).resolve()
        if sha256(artifact) != payload.get("fcpxml_sha256"):
            raise ValueError("fcpxml_identity")
        contract = parse_fcpxml_contract(artifact)
        target = str(payload.get("target_timeline_name") or "")
        expected = (payload.get("expected_clip_count"), payload.get("expected_duration_frames"), payload.get("expected_fps"))
        if target != contract["timeline_name"] or expected != (len(contract["clips"]), contract["duration_frames"], contract["fps"]):
            raise ValueError("artifact_contract")
        report["target_timeline_name"] = target
        if resolve is None:
            report["readiness"] = "BLOCKED_PHASE4B_RESOLVE_NOT_CONNECTED"
            return report
        manager = safe(resolve, "GetProjectManager")
        project = safe(manager, "GetCurrentProject")
        if project is None:
            report["readiness"] = "BLOCKED_PHASE4B_NO_CURRENT_PROJECT"
            return report
        report["project_name"] = str(safe(project, "GetName", default="") or "")
        current = safe(project, "GetCurrentTimeline")
        report["current_timeline_name"] = timeline_name(current) if current is not None else None
        report["media_pool_available"] = safe(project, "GetMediaPool") is not None
        declared_count = int(safe(project, "GetTimelineCount", default=0) or 0)
        timelines = project_timelines(project)
        names = [timeline_name(row) for row in timelines]
        report["timeline_count"] = declared_count
        report["timeline_names"] = names
        report["duplicate_name_counts"] = dict(sorted(Counter(names).items()))
        matches = find_timelines(project, target)
        report["target_occurrence_count"] = len(matches)
        try:
            if len(timelines) != declared_count:
                raise ValueError(f"timeline_inventory_incomplete:{len(timelines)}:{declared_count}")
            inventory = timeline_inventory(project)
            report["non_target_timeline_inventory"] = [row for row in inventory if row["name"] != target]
        except Exception as exc:
            report["failures"] = [f"{type(exc).__name__}: {exc}"]
            report["readiness"] = "BLOCKED_PHASE4B_SIGNATURE_BASELINE"
            return report
        if not report["media_pool_available"]:
            report["readiness"] = "BLOCKED_PHASE4B_MEDIA_POOL_UNAVAILABLE"
        elif len(matches) == 0:
            report["readiness"] = "READY_PHASE4B_FIRST_IMPORT"
        elif len(matches) > 1:
            report["readiness"] = "BLOCKED_PHASE4B_DUPLICATE_TARGET"
        else:
            try:
                report["target_validation"] = validate_target(matches[0], contract, target)
                report["readiness"] = "READY_PHASE4B_IDEMPOTENT_REUSE"
            except Exception as exc:
                report["target_validation"] = {"ok": False, "failure": f"{type(exc).__name__}: {exc}"}
                report["readiness"] = "BLOCKED_PHASE4B_TARGET_CONTRACT_MISMATCH"
    except Exception as exc:
        reason = re.sub(r"[^A-Z0-9]+", "_", str(exc).upper()).strip("_") or "UNEXPECTED_FAILURE"
        report["failures"] = [f"{type(exc).__name__}: {exc}"]
        report["readiness"] = f"BLOCKED_PHASE4B_{reason}"
    return report
