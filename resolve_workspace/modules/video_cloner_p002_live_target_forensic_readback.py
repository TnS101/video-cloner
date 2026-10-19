"""Read-only forensic classification of the existing P001 Resolve target."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Mapping


_spec = importlib.util.spec_from_file_location(
    "vc_phase6_application",
    Path(__file__).with_name("video_cloner_phase6_textplus_application.py"),
)
if _spec is None or _spec.loader is None:
    raise ImportError("cannot_load_phase6_application")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

TASK_ID = "VIDEO_CLONER_P002_LIVE_TARGET_FORENSIC_READBACK_V1"
MODE = "p002_readonly_existing_target_forensics"
ACTION = "inspect_existing_target_read_only"

MUTATION_COUNTS = {
    "timeline_imports": 0,
    "project_saves": 0,
    "timeline_selections": 0,
    "timeline_deletes": 0,
    "timeline_appends": 0,
    "title_writes": 0,
    "fusion_writes": 0,
    "media_imports": 0,
    "media_relinks": 0,
    "media_replaces": 0,
    "exports": 0,
    "renders": 0,
    "metadata_writes": 0,
}


def _identity(timeline: Any) -> dict[str, str | None] | None:
    if timeline is None:
        return None
    return {
        "name": str(base._safe(timeline, "GetName", default="") or ""),
        "unique_id": str(base._safe(timeline, "GetUniqueId", default="") or "") or None,
    }


def _validation(timeline: Any, contract: Mapping[str, Any], require_title_text: bool) -> dict[str, Any]:
    try:
        return {"ok": True, "failure": None, "result": base.validate_target(timeline, contract, require_title_text=require_title_text)}
    except Exception as exc:
        if isinstance(exc, base.TargetMismatch):
            return {"ok": False, "failure": f"ValueError: {exc.code}", "mismatch": exc.details, "result": None}
        return {"ok": False, "failure": f"{type(exc).__name__}: {exc}", "result": None}


def _overlay_evidence(snapshot: Mapping[str, Any], contract: Mapping[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    base_frame = snapshot["start_frame"]
    actual = [row for row in snapshot["items"] if row["track_type"] == "video" and row["track_index"] > 1]
    evidence: list[dict[str, Any]] = []
    exact = True
    for expected in list(contract["titles"]) + list(contract.get("flash_handoffs") or []):
        track = expected["lane"] + 1
        matches = [
            row for row in actual
            if row["track_index"] == track
            and row["start"] is not None
            and row["start"] - base_frame == expected["timeline_start"]
            and row["duration"] == expected["duration"]
        ]
        exact = exact and len(matches) == 1
        observed = matches[0] if len(matches) == 1 else {}
        evidence.append({
            "expected_text": expected["text"],
            "title_text": observed.get("title_text"),
            "media_path": observed.get("media_path"),
            "name": observed.get("name"),
            "track": track,
            "start": observed.get("start"),
            "end": observed.get("end"),
            "duration": observed.get("duration"),
            "match_count": len(matches),
        })
    return evidence, exact


def _classification(overlays: list[Mapping[str, Any]], exact_mapping: bool, strict: Mapping[str, Any], structural: Mapping[str, Any]) -> tuple[str, bool]:
    if any(row.get("media_path") for row in overlays):
        return "TITLE_MEDIA_PATH_CONTAMINATION", False
    if not structural.get("ok") or not exact_mapping:
        return "STRUCTURAL_TARGET_MISMATCH", False
    observed = [row.get("title_text") for row in overlays]
    if any(value is not None and value != row["expected_text"] for value, row in zip(observed, overlays)):
        return "DIRECT_TITLE_TEXT_MISMATCH", False
    if observed and all(value is None for value in observed):
        return "DIRECT_TITLE_TEXT_UNOBSERVABLE_STRUCTURALLY_VALID", True
    if strict.get("ok") and all(value is not None for value in observed):
        return "FORENSIC_EVIDENCE_INSUFFICIENT", False
    return "FORENSIC_EVIDENCE_INSUFFICIENT", False


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {
        "ok": False,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "classification": "FORENSIC_EVIDENCE_INSUFFICIENT",
        "fallback_eligible": False,
        "mutation_counts": dict(MUTATION_COUNTS),
        "zero_mutation_claim": True,
        "failures": [],
    }
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        required = {
            "action": ACTION,
            "read_only": True,
            "zero_mutation": True,
            "import_permitted": False,
            "save_project": False,
            "timeline_selection_permitted": False,
            "delete_permitted": False,
            "append_permitted": False,
            "title_write_permitted": False,
            "fusion_write_permitted": False,
            "media_import_permitted": False,
            "relink_permitted": False,
            "replace_permitted": False,
            "export_permitted": False,
            "render_permitted": False,
            "metadata_write_permitted": False,
            "retry_permitted": False,
        }
        if command.get("task") != TASK_ID or command.get("run_id") != run_id or command.get("mode") != MODE:
            raise ValueError("command_identity")
        if any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("read_only_authority")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        if not (root / "AGENTS.md").is_file():
            raise ValueError("repository_identity")
        contract = base.load_phase5_contract(root, Path(str(payload.get("manifest_path") or "")))
        declared = {
            "artifact_set_sha256": contract["artifact_set_sha256"],
            "textplus_fingerprint": contract["textplus_fingerprint"],
            "fcpxml_sha256": contract["fcpxml_sha256"],
            "report_sha256": contract["report_sha256"],
        }
        if any(payload.get(key) != value for key, value in declared.items()):
            raise ValueError("declared_artifact_identity")
        project_name = str(payload.get("expected_project") or "").strip()
        target_name = str(payload.get("target_timeline_name") or "").strip()
        if not project_name or not target_name or target_name != contract["xml"]["timeline_name"]:
            raise ValueError("explicit_target_identity")

        manager = base._safe(resolve, "GetProjectManager")
        project = base._safe(manager, "GetCurrentProject")
        actual_project = str(base._safe(project, "GetName", default="") or "") if project is not None else ""
        if project is None or actual_project != project_name:
            raise ValueError(f"project_identity:{actual_project}")
        pool = base._safe(project, "GetMediaPool")
        if pool is None:
            raise ValueError("media_pool_missing")

        current_before = _identity(base._safe(project, "GetCurrentTimeline"))
        timelines_before = base._timeline_inventory(project)
        media_before = base._media_pool_inventory(pool)
        matches = [row for row in base._timelines(project) if str(base._safe(row, "GetName", default="") or "") == target_name]
        if len(matches) != 1:
            raise ValueError(f"target_identity:{len(matches)}")
        target = matches[0]
        target_uid = base._unique_id(target)
        if not target_uid:
            raise ValueError("target_unique_id")
        snapshot = base.timeline_snapshot(target)
        overlays, exact_mapping = _overlay_evidence(snapshot, contract["xml"])
        strict = _validation(target, contract["xml"], True)
        structural = _validation(target, contract["xml"], False)
        classification, fallback_eligible = _classification(overlays, exact_mapping, strict, structural)

        current_after = _identity(base._safe(project, "GetCurrentTimeline"))
        timelines_after = base._timeline_inventory(project)
        media_after = base._media_pool_inventory(pool)
        state_unchanged = current_after == current_before and timelines_after == timelines_before and media_after == media_before
        if not state_unchanged:
            raise ValueError("resolve_state_drift")
        result.update({
            "ok": True,
            "classification": classification,
            "fallback_eligible": fallback_eligible,
            "project_name": actual_project,
            "target_timeline_name": target_name,
            "target_unique_id": target_uid,
            "target_snapshot": snapshot,
            "overlay_evidence": overlays,
            "overlay_mapping_exact": exact_mapping,
            "strict_validation": strict,
            "structural_validation": structural,
            "current_timeline_before": current_before,
            "current_timeline_after": current_after,
            "timeline_inventory_before": timelines_before,
            "timeline_inventory_after": timelines_after,
            "media_pool_inventory_before": media_before,
            "media_pool_inventory_after": media_after,
            "current_timeline_unchanged": True,
            "timeline_inventory_unchanged": True,
            "media_pool_inventory_unchanged": True,
            **declared,
        })
    except Exception as exc:
        result["failures"] = [f"{type(exc).__name__}: {exc}"]
    return result
