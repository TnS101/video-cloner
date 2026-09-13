"""Manifest-aware, read-only Phase 6 Resolve preflight."""
from __future__ import annotations

from collections import Counter
import importlib.util
from pathlib import Path
from typing import Any, Mapping


_spec = importlib.util.spec_from_file_location(
    "vc_phase6_for_readonly_preflight",
    Path(__file__).with_name("video_cloner_phase6_textplus_application.py"),
)
if _spec is None or _spec.loader is None:
    raise ImportError("cannot_load_phase6_application")
_phase6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_phase6)

TASK_ID = "VIDEO_CLONER_PHASE6_READONLY_PREFLIGHT_V1"
MODE = "phase6_readonly_preflight"
ACTION = "inspect_textplus_full_readiness"
ZERO_MUTATIONS = {
    "imports": 0,
    "saves": 0,
    "timeline_deletes": 0,
    "media_deletes": 0,
    "relinks": 0,
    "replaces": 0,
    "metadata_effect_mutations": 0,
    "current_timeline_restores": 0,
}


def _timeline_identity(timeline: Any) -> dict[str, str | None] | None:
    if timeline is None:
        return None
    return {
        "name": str(_phase6._safe(timeline, "GetName", default="") or ""),
        "unique_id": str(_phase6._safe(timeline, "GetUniqueId", default="") or "") or None,
    }


def _title_readback(inventory: list[dict[str, Any]], exact_target: bool) -> dict[str, Any]:
    rows = [
        item
        for timeline in inventory
        for item in timeline["items"]
        if item["track_type"] == "video" and item["track_index"] > 1 and item.get("title_text") is not None
    ]
    complete = all(
        row.get("name") and row.get("start") is not None and row.get("end") is not None
        and row.get("duration") is not None and row.get("title_text") is not None
        for row in rows
    )
    sufficient = exact_target or bool(rows and complete)
    return {
        "sufficient": sufficient,
        "status": "EXACT_TARGET_VALIDATED" if exact_target else ("OBSERVED_COMPLETE_TITLE_READBACK" if sufficient else "UNPROVEN_TITLE_READBACK"),
        "observed_title_count": len(rows),
        "lane_from_track_index": True,
        "caption_identity_field": "timeline_item_name",
        "text_available": bool(rows) and all(row.get("title_text") is not None for row in rows),
        "timing_available": bool(rows) and all(row.get("start") is not None and row.get("end") is not None and row.get("duration") is not None for row in rows),
    }


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    report: dict[str, Any] = {
        "ok": False,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "action": ACTION,
        "read_only": True,
        "selected_node": _phase6.NODE,
        "package_verified": False,
        "classification": "LIVE_IMPORT_BLOCKED",
        "target_state": None,
        "mutation_counts": dict(ZERO_MUTATIONS),
        "failures": [],
    }
    project = None
    current_before = None
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        if command.get("task") != TASK_ID or command.get("run_id") != run_id or command.get("mode") != MODE or payload.get("action") != ACTION:
            raise ValueError("command_identity")
        if payload.get("read_only") is not True or any(payload.get(key) is not False for key in (
            "mutation_permitted", "import_permitted", "save_project", "delete_permitted",
            "relink_permitted", "replace_permitted", "metadata_controller_permitted",
        )):
            raise ValueError("read_only_authority")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        if not (root / "AGENTS.md").is_file():
            raise ValueError("repository_identity")
        contract = _phase6.load_phase5_contract(root, Path(str(payload.get("manifest_path") or "")))
        declared = {
            "artifact_set_sha256": contract["artifact_set_sha256"],
            "textplus_fingerprint": contract["textplus_fingerprint"],
            "fcpxml_sha256": contract["fcpxml_sha256"],
            "report_sha256": contract["report_sha256"],
        }
        if payload.get("selected_node") != _phase6.NODE or any(payload.get(key) != value for key, value in declared.items()):
            raise ValueError("declared_artifact_identity")
        expected_project = str(payload.get("expected_project") or "").strip()
        target_name = str(payload.get("target_timeline_name") or "").strip()
        if not expected_project or target_name != contract["xml"]["timeline_name"]:
            raise ValueError("explicit_target_identity")
        report.update({
            "package_verified": True,
            "manifest_path": str(contract["manifest_path"]),
            "expected_project": expected_project,
            "target_timeline_name": target_name,
            "phase5_contract": _phase6.NODE_CONTRACT,
            "v2_title_count": len(contract["xml"]["titles"]),
            "v2_title_lanes": contract["xml"]["title_lanes"],
            "flash_handoff_count": len(contract["xml"].get("flash_handoffs") or []),
            **declared,
        })

        manager = _phase6._safe(resolve, "GetProjectManager")
        project = _phase6._safe(manager, "GetCurrentProject")
        actual_project = str(_phase6._safe(project, "GetName", default="") or "") if project is not None else ""
        report["actual_project"] = actual_project
        if project is None or actual_project != expected_project:
            raise ValueError(f"project_identity:{actual_project}")
        pool = _phase6._safe(project, "GetMediaPool")
        if pool is None:
            raise ValueError("media_pool_missing")
        current_before = _phase6._safe(project, "GetCurrentTimeline")
        report["current_timeline_before"] = _timeline_identity(current_before)
        timelines = _phase6._timeline_inventory(project)
        media = _phase6._media_pool_inventory(pool)
        matches = [row for row in _phase6._timelines(project) if str(_phase6._safe(row, "GetName", default="") or "") == target_name]
        report.update({
            "timeline_count": len(timelines),
            "timeline_inventory": timelines,
            "target_match_count": len(matches),
            "protected_timeline_signatures": [row["signature"] for row in timelines if row["name"] != target_name],
            "media_pool_inventory": media,
            "media_pool_count": len(media),
        })
        target_validation = None
        if len(matches) == 0:
            target_state = "ABSENT"
        elif len(matches) > 1:
            target_state = "AMBIGUOUS_DUPLICATE"
        else:
            try:
                target_validation = _phase6.validate_target(matches[0], contract["xml"])
                target_state = "EXACT_REUSE_CANDIDATE"
            except Exception as exc:
                target_state = "INCOMPATIBLE_EXISTING"
                target_validation = {"ok": False, "failure": f"{type(exc).__name__}: {exc}"}
        capability = _title_readback(timelines, target_state == "EXACT_REUSE_CANDIDATE")
        report.update({"target_state": target_state, "target_validation": target_validation, "v2_readback_capability": capability})

        timelines_after = _phase6._timeline_inventory(project)
        media_after = _phase6._media_pool_inventory(pool)
        timeline_key = lambda row: (row["name"], row["unique_id"], row["signature"])
        if Counter(map(timeline_key, timelines_after)) != Counter(map(timeline_key, timelines)):
            raise ValueError("timeline_state_changed")
        if Counter(row["signature"] for row in media_after) != Counter(row["signature"] for row in media):
            raise ValueError("media_state_changed")
        report["protected_state_unchanged"] = True
        if target_state == "EXACT_REUSE_CANDIDATE":
            report["classification"] = "LIVE_EXACT_REUSE_CANDIDATE"
        elif target_state == "ABSENT" and capability["sufficient"]:
            report["classification"] = "LIVE_IMPORT_PRECONDITIONS_PASS"
        report["ok"] = True
    except Exception as exc:
        report["failures"] = [f"{type(exc).__name__}: {exc}"]
    finally:
        if project is not None and current_before is not None:
            current_after = _phase6._safe(project, "GetCurrentTimeline")
            if _timeline_identity(current_after) != _timeline_identity(current_before):
                report["mutation_counts"]["current_timeline_restores"] = 1
                if not bool(_phase6._safe(project, "SetCurrentTimeline", current_before, default=False)):
                    report["ok"] = False
                    report["classification"] = "LIVE_IMPORT_BLOCKED"
                    report["failures"].append("ValueError: current_timeline_restore")
            report["current_timeline_after"] = _timeline_identity(_phase6._safe(project, "GetCurrentTimeline"))
    return report
