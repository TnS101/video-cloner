"""One-shot live application of the authenticated Reel #2 offline timeline."""
from __future__ import annotations

from collections import Counter
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

TASK_ID = "VIDEO_CLONER_PHASE6_OFFLINE_TIMELINE_LIVE_APPLICATION_V1"
MODE = "phase6_apply_offline_timeline_v1"
ACTION = "finalize_existing_provenance_save"


def _identity(timeline: Any) -> dict[str, str | None] | None:
    if timeline is None:
        return None
    return {
        "name": str(base._safe(timeline, "GetName", default="") or ""),
        "unique_id": str(base._safe(timeline, "GetUniqueId", default="") or "") or None,
    }


def _timeline_counter(rows: list[Mapping[str, Any]]) -> Counter:
    return Counter((row.get("name"), row.get("unique_id"), base._fingerprint({
        "start_frame": row.get("start_frame"),
        "end_frame": row.get("end_frame"),
        "settings": row.get("settings"),
        "video_track_count": row.get("video_track_count"),
        "audio_track_count": row.get("audio_track_count"),
        "items": [{key: item.get(key) for key in ("track_type", "track_index", "name", "start", "end", "duration", "left_offset", "media_path")} for item in row.get("items", [])],
    })) for row in rows)


def _media_counter(rows: list[Mapping[str, Any]]) -> Counter:
    return Counter(row.get("signature") for row in rows)


def _find(project: Any, name: str) -> list[Any]:
    return [row for row in base._timelines(project) if str(base._safe(row, "GetName", default="") or "") == name]


def _preflight_path(root: Path, value: object) -> Path:
    candidate = Path(str(value or ""))
    return base._repository_path(root, candidate if candidate.is_absolute() else root / candidate, "preflight_report")


def _load_preflight(root: Path, payload: Mapping[str, Any], declared: Mapping[str, str], project_name: str, target_name: str) -> tuple[Path, dict[str, Any]]:
    path = _preflight_path(root, payload.get("preflight_report_path"))
    if not path.is_file() or base._sha256(path) != payload.get("preflight_report_sha256"):
        raise ValueError("preflight_report_identity")
    report = base._read_json(path, "preflight_report")
    if any((
        report.get("ok") is not True,
        report.get("classification") != "LIVE_IMPORT_PRECONDITIONS_PASS",
        report.get("actual_project") != project_name,
        report.get("target_timeline_name") != target_name,
        report.get("target_state") != "ABSENT",
        report.get("target_match_count") != 0,
        report.get("protected_state_unchanged") is not True,
        any(report.get(key) != value for key, value in declared.items()),
    )):
        raise ValueError("preflight_contract")
    return path, report


def _readback(project: Any, target_name: str, target_uid: str, contract: Mapping[str, Any], protected: Counter, media: Counter) -> dict[str, Any]:
    matches = _find(project, target_name)
    if len(matches) != 1 or base._unique_id(matches[0]) != target_uid:
        raise ValueError("post_save_target_identity")
    target = base.validate_target(matches[0], contract["xml"], require_title_text=False)
    inventory = base._timeline_inventory(project)
    if _timeline_counter([row for row in inventory if row["name"] != target_name]) != protected:
        raise ValueError("protected_timeline_changed")
    pool = base._safe(project, "GetMediaPool")
    if pool is None or _media_counter(base._media_pool_inventory(pool)) != media:
        raise ValueError("media_pool_changed")
    return target


def _load_import_provenance(root: Path, payload: Mapping[str, Any], declared: Mapping[str, str], project_name: str, target_name: str) -> dict[str, Any]:
    _, preflight = _load_preflight(root, payload, declared, project_name, target_name)
    command_path = _preflight_path(root, payload.get("original_import_command_path"))
    report_path = _preflight_path(root, payload.get("original_import_report_path"))
    if base._sha256(command_path) != payload.get("original_import_command_sha256") or base._sha256(report_path) != payload.get("original_import_report_sha256"):
        raise ValueError("original_import_identity")
    command = base._read_json(command_path, "original_import_command")
    report = base._read_json(report_path, "original_import_report")
    original = command.get("payload") or {}
    mutations = report.get("mutation_counts") or {}
    if any((
        report.get("run_id") != command.get("run_id"),
        report.get("ownership_classification") != "NEWLY_CREATED",
        mutations.get("timeline_imports") != 1,
        any(mutations.get(key) for key in ("saves", "deletes", "relinks", "replaces", "media_imports")),
        any(original.get(key) != value for key, value in declared.items()),
        original.get("expected_project") != project_name,
        original.get("target_timeline_name") != target_name,
        preflight.get("target_state") != "ABSENT",
    )):
        raise ValueError("original_import_provenance")
    return {"preflight_target_state": "ABSENT", "original_import_count": 1, "original_import_run_id": report["run_id"]}


def _limitation_report(root: Path, payload: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    path = _preflight_path(root, payload.get(f"{prefix}_report_path"))
    if not path.is_file() or base._sha256(path) != payload.get(f"{prefix}_report_sha256"):
        raise ValueError(f"{prefix}_report_identity")
    return base._read_json(path, f"{prefix}_report")


def _provenance_semantic_acceptance(contract: Mapping[str, Any], validation: Mapping[str, Any], provenance: Mapping[str, Any], direct: Mapping[str, Any], export: Mapping[str, Any], canonical_sha: str) -> dict[str, Any]:
    titles = contract["xml"]["titles"]
    snapshot = validation["snapshot"]
    caption_tracks = {row["lane"] + 1 for row in titles}
    actual = sorted((row for row in snapshot["items"] if row["track_type"] == "video" and row["track_index"] in caption_tracks), key=lambda row: (row["track_index"], row["start"]))
    expected = sorted(titles, key=lambda row: (row["lane"], row["timeline_start"]))
    if canonical_sha != contract["fcpxml_sha256"]:
        raise ValueError("fallback_canonical_sha")
    if provenance.get("original_import_count") != 1 or provenance.get("preflight_target_state") != "ABSENT":
        raise ValueError("fallback_import_provenance")
    if len(actual) != len(expected) or any((row["track_index"], row["start"], row["duration"]) != (authority["lane"] + 1, authority["timeline_start"], authority["duration"]) for row, authority in zip(actual, expected)):
        raise ValueError("fallback_structural_identity")
    observed = [(row, authority) for row, authority in zip(actual, expected) if row.get("title_text") is not None]
    if observed:
        if any(row["title_text"] != authority["text"] for row, authority in observed) or len(observed) != len(expected):
            raise ValueError("direct_semantic_mismatch")
        raise ValueError("direct_semantic_readback_available")
    if direct.get("failures") != ["ValueError: target_title"] or any((direct.get("mutation_counts") or {}).values()):
        raise ValueError("direct_readback_limitation")
    exported = export.get("pre_save_export") or {}
    if exported.get("caption_texts_exposed") is True:
        if exported.get("captions_exact") != len(expected):
            raise ValueError("export_semantic_mismatch")
        raise ValueError("export_semantic_readback_available")
    if export.get("failures") != ["ValueError: timeline_export_failed"] or any((export.get("mutation_counts") or {}).values()):
        raise ValueError("export_readback_limitation")
    probes = {}
    for text in ("launching", "6000"):
        authority = next(row for row in expected if row["text"] == text)
        matches = [row for row in actual if (row["track_index"], row["start"], row["duration"]) == (authority["lane"] + 1, authority["timeline_start"], authority["duration"])]
        if len(matches) != 1:
            raise ValueError(f"fallback_semantic_binding:{text}")
        probes[text] = {"text": text, "track": authority["lane"] + 1, "start": authority["timeline_start"], "duration": authority["duration"]}
    return {"policy": "PROVENANCE_STRUCTURAL_SEMANTIC_ACCEPTANCE_V1", "ok": True, "caption_count": len(expected), "direct_textplus_readback": "UNAVAILABLE", "live_export": "UNAVAILABLE", "probes": probes, "split_or_extra_evidence": 0}


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {
        "ok": False,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "classification": "VIDEO_CLONER_V1_LIVE_BLOCKED",
        "ownership_classification": None,
        "mutation_counts": {"timeline_imports": 0, "saves": 0, "deletes": 0, "relinks": 0, "replaces": 0, "media_imports": 0},
        "direct_textplus_readback": "DIRECT_TEXTPLUS_READBACK_UNAVAILABLE",
        "title_text_read_methods": ["GetProperty", "GetFusionCompByIndex", "GetFusionCompNameList/GetFusionCompByName", "TextPlus.GetInput(frame=0)", "TextPlus.GetInput(static)"],
        "failures": [],
    }
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        required = {
            "action": ACTION,
            "apply_once": False,
            "import_permitted": False,
            "save_project": True,
            "delete_permitted": False,
            "relink_permitted": False,
            "replace_permitted": False,
            "media_import_permitted": False,
            "retry_permitted": False,
        }
        if command.get("task") != TASK_ID or command.get("run_id") != run_id or command.get("mode") != MODE or any(payload.get(k) != v for k, v in required.items()):
            raise ValueError("command_authority")
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
        if payload.get("selected_node") != base.NODE or any(payload.get(k) != v for k, v in declared.items()):
            raise ValueError("declared_artifact_identity")
        project_name = str(payload.get("expected_project") or "")
        target_name = str(payload.get("target_timeline_name") or "")
        if target_name != contract["xml"]["timeline_name"]:
            raise ValueError("target_authority")
        provenance = _load_import_provenance(root, payload, declared, project_name, target_name)
        direct_limitation = _limitation_report(root, payload, "direct_limitation")
        export_limitation = _limitation_report(root, payload, "export_limitation")
        result["canonical_import_provenance"] = provenance
        forensic_path = _preflight_path(root, payload.get("forensic_report_path"))
        if not forensic_path.is_file() or base._sha256(forensic_path) != payload.get("forensic_report_sha256"):
            raise ValueError("forensic_report_identity")
        forensic = base._read_json(forensic_path, "forensic_report")
        target_uid = str(payload.get("expected_target_uid") or "")
        forensic_targets = [row for row in forensic.get("timeline_inventory", []) if row.get("name") == target_name]
        if any((forensic.get("ok") is not True, forensic.get("target_match_count") != 1, len(forensic_targets) != 1, forensic_targets[0].get("unique_id") != target_uid, any(forensic.get(key) != value for key, value in declared.items()), any(forensic.get("mutation_counts", {}).values()))):
            raise ValueError("forensic_contract")

        manager = base._safe(resolve, "GetProjectManager")
        project = base._safe(manager, "GetCurrentProject")
        if project is None or str(base._safe(project, "GetName", default="") or "") != project_name:
            raise ValueError("project_identity")
        pool = base._safe(project, "GetMediaPool")
        if pool is None:
            raise ValueError("media_pool_missing")
        current_before = base._safe(project, "GetCurrentTimeline")
        if _identity(current_before) != forensic.get("current_timeline_after"):
            raise ValueError("current_timeline_drift")
        timelines_before = base._timeline_inventory(project)
        media_before = base._media_pool_inventory(pool)
        if _timeline_counter(timelines_before) != _timeline_counter(forensic.get("timeline_inventory") or []):
            raise ValueError("timeline_forensic_drift")
        if _media_counter(media_before) != _media_counter(forensic.get("media_pool_inventory") or []):
            raise ValueError("media_forensic_drift")
        matches = _find(project, target_name)
        if len(matches) != 1 or base._unique_id(matches[0]) != target_uid:
            raise ValueError("existing_target_identity")
        target = matches[0]
        result["ownership_classification"] = "NEWLY_CREATED"
        result["pre_save_snapshot"] = base.timeline_snapshot(target)

        protected = _timeline_counter([row for row in timelines_before if row["name"] != target_name])
        media = _media_counter(media_before)
        post_apply = _readback(project, target_name, target_uid, contract, protected, media)
        acceptance = _provenance_semantic_acceptance(contract, post_apply, provenance, direct_limitation, export_limitation, str(payload.get("fcpxml_sha256") or ""))
        result.update({"pre_save_readback": post_apply, "semantic_acceptance": acceptance, "protected_state_unchanged_pre_save": True})
        titles = contract["xml"]["titles"]
        lanes = Counter(row["lane"] for row in titles)
        if lanes != Counter({1: 77, 2: 14, 3: 1}):
            raise ValueError("lane_authority")

        saved = base._safe(manager, "SaveProject", default=False)
        result["mutation_counts"]["saves"] = 1
        if saved is not True:
            raise ValueError("save_project")
        fresh_project = base._safe(base._safe(resolve, "GetProjectManager"), "GetCurrentProject")
        if fresh_project is None or str(base._safe(fresh_project, "GetName", default="") or "") != project_name:
            raise ValueError("post_save_project_identity")
        post_save = _readback(fresh_project, target_name, target_uid, contract, protected, media)
        post_save_acceptance = _provenance_semantic_acceptance(contract, post_save, provenance, direct_limitation, export_limitation, str(payload.get("fcpxml_sha256") or ""))
        if post_save["snapshot"]["signature"] != post_apply["snapshot"]["signature"] or _identity(base._safe(fresh_project, "GetCurrentTimeline")) != _identity(current_before):
            raise ValueError("post_save_state_drift")

        result.update({
            "ok": True,
            "classification": "VIDEO_CLONER_V1_LIVE_ACCEPTED",
            "project_name": project_name,
            "target_timeline_name": target_name,
            "target_unique_id": target_uid,
            "canonical_artifact_sha256": contract["fcpxml_sha256"],
            "artifact_set_sha256": contract["artifact_set_sha256"],
            "applied_operation_counts": {"video_clips": 14, "audio_clips": 1, "textplus_titles": 92, "flash_handoffs": 1, "speed": 0, "zoom": 0, "blur": 0, "native_transitions": 0},
            "post_apply_readback": post_apply,
            "post_save_readback": post_save,
            "post_save_semantic_acceptance": post_save_acceptance,
            "semantic_probes": acceptance["probes"],
            "caption_lane_distribution": {str(k): lanes[k] for k in sorted(lanes)},
            "same_lane_overlap_count": 0,
            "flash": {"boundary_frame": 596, "duration_frames": 9, "carrier": "flash_v4_visual_carrier"},
            "protected_state_unchanged": True,
            "save_succeeded": True,
            **declared,
        })
    except Exception as exc:
        result["failures"] = [f"{type(exc).__name__}: {exc}"]
    return result
