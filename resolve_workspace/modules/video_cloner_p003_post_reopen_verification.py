"""Strictly read-only P003 post-reopen persistence verification."""
from __future__ import annotations

from collections import Counter
import importlib.util
from pathlib import Path
import subprocess
from typing import Any, Mapping


_spec = importlib.util.spec_from_file_location(
    "vc_phase6_application",
    Path(__file__).with_name("video_cloner_phase6_textplus_application.py"),
)
if _spec is None or _spec.loader is None:
    raise ImportError("cannot_load_phase6_application")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

TASK_ID = "VIDEO_CLONER_P003_POST_REOPEN_VERIFICATION_V1"
MODE = "p003_readonly_post_reopen_verification"
ACTION = "verify_saved_p001_target_read_only"
FINALIZER_TASK_ID = "VIDEO_CLONER_P003_FALLBACK_PERSISTENCE_FINALIZER_V1"
FINALIZER_MODE = "p003_evidence_bound_fallback_save"
POLICY = "PROVENANCE_STRUCTURAL_SEMANTIC_ACCEPTANCE_V1"
P001_RUN_ID = "20261007T173351920Z_b031b0693f6f4c7d8f8d17c6d718ce41"
P002_RUN_ID = "20261008T071035670Z_46adb9a1733448e3b6ff82b42b2e7de2"
PROJECT_NAME = "New Project 1"
TARGET_NAME = "VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B"
TARGET_UID = "4aaa91c0-c434-4439-a15a-92ce86e80256"

MUTATION_COUNTS = {
    "project_saves": 0,
    "timeline_imports": 0,
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


def _git_value(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise ValueError("repository_git_identity")
    return completed.stdout.strip()


def _repository_path(root: Path, value: object, label: str) -> Path:
    candidate = Path(str(value or ""))
    return base._repository_path(root, candidate if candidate.is_absolute() else root / candidate, label)


def _saved_baseline(root: Path, payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    report_path = _repository_path(root, payload.get("finalizer_report_path"), "finalizer_report")
    if not report_path.is_file() or base._sha256(report_path) != payload.get("finalizer_report_sha256"):
        raise ValueError("finalizer_report_identity")
    report = base._read_json(report_path, "finalizer_report")
    state = report.get("post_save_state") or {}
    acceptance = report.get("post_save_semantic_acceptance") or {}
    timelines = state.get("timeline_inventory") or []
    media = state.get("media_pool_inventory") or []
    targets = [row for row in timelines if row.get("name") == TARGET_NAME]
    gold = [row for row in timelines if row.get("name") == "DcJRJtUKScu_offline_timeline_v1"]
    if any((
        report.get("ok") is not True,
        report.get("task_id") != FINALIZER_TASK_ID,
        report.get("mode") != FINALIZER_MODE,
        report.get("run_id") != payload.get("expected_finalizer_run_id"),
        report.get("classification") != "P003_FALLBACK_SAVE_ACCEPTED",
        report.get("project_name") != PROJECT_NAME,
        report.get("target_timeline_name") != TARGET_NAME,
        report.get("target_unique_id") != TARGET_UID,
        report.get("p001_run_id") != P001_RUN_ID,
        report.get("p002_run_id") != P002_RUN_ID,
        report.get("mutation_counts") != {
            "timeline_imports": 0, "saves": 1, "timeline_selections": 0, "timeline_deletes": 0,
            "timeline_appends": 0, "title_writes": 0, "fusion_writes": 0, "media_imports": 0,
            "media_relinks": 0, "media_replaces": 0, "exports": 0, "renders": 0, "metadata_writes": 0,
        },
        report.get("save_succeeded") is not True,
        report.get("protected_state_unchanged") is not True,
        acceptance.get("policy") != POLICY,
        acceptance.get("ok") is not True,
        acceptance.get("p001_run_id") != P001_RUN_ID,
        acceptance.get("p002_run_id") != P002_RUN_ID,
        len(timelines) != 46,
        len([row for row in timelines if row.get("name") != TARGET_NAME]) != 45,
        len(media) != 55,
        len(targets) != 1 or targets[0].get("unique_id") != TARGET_UID,
        len(gold) != 1 or gold[0].get("unique_id") != "4ad2a3c3-031c-464d-96aa-76a045608ad6",
        not (state.get("target_validation") or {}).get("ok"),
    )):
        raise ValueError("finalizer_report_contract")
    return report, state


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {
        "ok": False,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "classification": "P003_POST_REOPEN_BLOCKED",
        "mutation_counts": dict(MUTATION_COUNTS),
        "failures": [],
    }
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        required = {
            "action": ACTION,
            "read_only": True,
            "zero_mutation": True,
            "save_project": False,
            "import_permitted": False,
            "timeline_selection_permitted": False,
            "delete_permitted": False,
            "rename_permitted": False,
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
        if command.get("task") != TASK_ID or command.get("run_id") != run_id or command.get("mode") != MODE or any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("read_only_authority")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        if not (root / "AGENTS.md").is_file():
            raise ValueError("repository_identity")
        if _git_value(root, "branch", "--show-current") != "main" or _git_value(root, "rev-parse", "HEAD") != payload.get("expected_repository_head"):
            raise ValueError("repository_git_identity")
        if base._sha256(Path(__file__).resolve()) != payload.get("verifier_module_sha256"):
            raise ValueError("verifier_module_identity")
        manifest = _repository_path(root, payload.get("manifest_path"), "manifest")
        if not manifest.is_file() or base._sha256(manifest) != payload.get("manifest_sha256"):
            raise ValueError("manifest_identity")
        contract = base.load_phase5_contract(root, manifest)
        declared = {key: contract[key] for key in ("artifact_set_sha256", "textplus_fingerprint", "fcpxml_sha256", "report_sha256")}
        if any(payload.get(key) != value for key, value in declared.items()):
            raise ValueError("declared_artifact_identity")
        if (payload.get("expected_project"), payload.get("target_timeline_name"), payload.get("expected_target_uid")) != (PROJECT_NAME, TARGET_NAME, TARGET_UID):
            raise ValueError("target_authority")
        _, saved = _saved_baseline(root, payload)

        manager = base._safe(resolve, "GetProjectManager")
        project = base._safe(manager, "GetCurrentProject")
        if project is None or str(base._safe(project, "GetName", default="") or "") != PROJECT_NAME:
            raise ValueError("project_identity")
        pool = base._safe(project, "GetMediaPool")
        if pool is None:
            raise ValueError("media_pool_missing")
        matches = [row for row in base._timelines(project) if str(base._safe(row, "GetName", default="") or "") == TARGET_NAME]
        if len(matches) != 1 or base._unique_id(matches[0]) != TARGET_UID:
            raise ValueError("target_persistence_drift")
        validation = base.validate_target(matches[0], contract["xml"], require_title_text=False)
        timelines = base._timeline_inventory(project)
        media = base._media_pool_inventory(pool)
        if validation["snapshot"]["signature"] != saved["target_validation"]["snapshot"]["signature"]:
            raise ValueError("target_persistence_drift")
        if _timeline_counter(timelines) != _timeline_counter(saved["timeline_inventory"]):
            raise ValueError("protected_timeline_drift")
        if _media_counter(media) != _media_counter(saved["media_pool_inventory"]):
            raise ValueError("media_pool_drift")

        result.update({
            "ok": True,
            "classification": "P003_POST_REOPEN_PERSISTENCE_VERIFIED",
            "project_name": PROJECT_NAME,
            "target_timeline_name": TARGET_NAME,
            "target_unique_id": TARGET_UID,
            "current_timeline": _identity(base._safe(project, "GetCurrentTimeline")),
            "target_validation": validation,
            "timeline_inventory": timelines,
            "media_pool_inventory": media,
            "p001_run_id": P001_RUN_ID,
            "p002_run_id": P002_RUN_ID,
            "semantic_acceptance_policy": POLICY,
            **declared,
        })
    except Exception as exc:
        result["failures"] = [f"{type(exc).__name__}: {exc}"]
    return result
