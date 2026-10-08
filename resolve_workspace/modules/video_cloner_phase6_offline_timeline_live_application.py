"""One-shot live application of the authenticated Reel #2 offline timeline."""
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

TASK_ID = "VIDEO_CLONER_P003_FALLBACK_PERSISTENCE_FINALIZER_V1"
MODE = "p003_evidence_bound_fallback_save"
ACTION = "finalize_existing_p001_target_once"
POLICY = "PROVENANCE_STRUCTURAL_SEMANTIC_ACCEPTANCE_V1"
P001_RUN_ID = "20261007T173351920Z_b031b0693f6f4c7d8f8d17c6d718ce41"
P002_RUN_ID = "20261008T071035670Z_46adb9a1733448e3b6ff82b42b2e7de2"
PROJECT_NAME = "New Project 1"
TARGET_NAME = "VIDEO_CLONER_P001_DZatr0EJt4B_20261007_4CE37F9BC61B"
TARGET_UID = "4aaa91c0-c434-4439-a15a-92ce86e80256"
GOLD_NAME = "DcJRJtUKScu_offline_timeline_v1"
GOLD_UID = "4ad2a3c3-031c-464d-96aa-76a045608ad6"
GOLD_DRT_SHA256 = "99b11b92d55c40682f630fd4c52072e006c7e0b6494aef367bda175fb9d4af2e"
MANIFEST_SHA256 = "38e57cfd57eafb4956f7a54ea86b8f3819d3ba5b1ab3b8b7d47d0d37fe38a615"

EVIDENCE_FILES = {
    "manifest": (".project_ops/artifacts/P001_LIVE_RESOLVE_ACCEPTANCE/T001/P001_acceptance_fresh_4CE37F9BC61B_manifest.json", MANIFEST_SHA256),
    "p001_command": (f".agent/commands/failed/VIDEO_CLONER_PHASE6_TEXTPLUS_APPLICATION_V1_{P001_RUN_ID}.json", "3f8f78df42275aa2ec57a2ea67e3f7bd8676c0a62e1ab5fb055c363dfabfd492"),
    "p001_report": (f".agent/reports/VIDEO_CLONER_PHASE6_TEXTPLUS_APPLICATION_V1/{P001_RUN_ID}/report.json", "2871997ed5eba7d1e98e81647ac534ee5ae5dd1e5cf1699a716e1e3470b21bae"),
    "p001_status": (f".agent/reports/VIDEO_CLONER_PHASE6_TEXTPLUS_APPLICATION_V1/{P001_RUN_ID}/status.json", "09bceeff9adefbb37748a60d72ef7e5e133847829bf44522428fe488398752c1"),
    "p001_log": (f".agent/reports/VIDEO_CLONER_PHASE6_TEXTPLUS_APPLICATION_V1/{P001_RUN_ID}/run.log", "ed9b2fb0d25ae403c6d9789e67cadd6395d2172cd145ac45961ea02d61e10a80"),
    "p001_t002": (".project_ops/reports/P001_LIVE_RESOLVE_ACCEPTANCE/T002/REPORT.md", "c4c89e34410b913adbd4f2d1951461d298aec25e8b20dd31c99aa9ab95c2bd93"),
    "p001_preflight": (".project_ops/reports/P001_LIVE_RESOLVE_ACCEPTANCE/T001/PREFLIGHT_EVIDENCE.json", "17fb59e85239a68c14760b31a42aa8996e899e15fbe81a2f053dc44f0890e975"),
    "p002_command": (f".agent/commands/completed/VIDEO_CLONER_P002_LIVE_TARGET_FORENSIC_READBACK_V1_{P002_RUN_ID}.json", "38bd1cc74927d8ae1a74e822aa8689b17c09aceae445b10edafd5f7efbc91fbb"),
    "p002_report": (f".agent/reports/VIDEO_CLONER_P002_LIVE_TARGET_FORENSIC_READBACK_V1/{P002_RUN_ID}/report.json", "862bfc4e26ebbb77587a05dbe6b8792ef2071adf1089780b0e92f4e57cd0cac5"),
    "p002_status": (f".agent/reports/VIDEO_CLONER_P002_LIVE_TARGET_FORENSIC_READBACK_V1/{P002_RUN_ID}/status.json", "5936d9edf74f3d27350a14df373671ab759410435a9f03efe96e9e3b02b7d1f3"),
    "p002_log": (f".agent/reports/VIDEO_CLONER_P002_LIVE_TARGET_FORENSIC_READBACK_V1/{P002_RUN_ID}/run.log", "0873383ce54536d5bc6ce61b61ccba81beaa1404c79ca45b21f59bc2e87dcd88"),
    "p002_t001": (".project_ops/reports/P002_LIVE_TARGET_FORENSIC_READBACK/T001/REPORT.md", "2d12baccbfcca21d54314eeb7eb0692f64b627222e4fce19e507dbd0bed85792"),
    "p002_t002": (".project_ops/reports/P002_LIVE_TARGET_FORENSIC_READBACK/T002/REPORT.md", "50a0d1fe83d0ac03d78f9beed85c88c1e63cc4fb17a9662130b027b421493a34"),
    "p002_t003": (".project_ops/reports/P002_LIVE_TARGET_FORENSIC_READBACK/T003/REPORT.md", "9d3d35775306568451a0c5a08afef98409fce9287c62e0c0c0b937979a2065ac"),
    "p002_module": ("resolve_workspace/modules/video_cloner_p002_live_target_forensic_readback.py", "7ccfdd8593a65428f13fe408899d7f872131b5730ff999e928e7f7af3f0f4b10"),
    "frozen_importer": ("resolve_workspace/modules/video_cloner_phase6_textplus_application.py", "45a727eed118d3e9d31646f5c962e5b0af17557be20247cadea2d5d13f0680d4"),
    "gold_drt": (".agent/gold/video_cloner/reel2/captions/VIDEO_CLONER_REEL2_CAPTIONS_GOLD_HUMAN_ACCEPTED.drt", GOLD_DRT_SHA256),
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


def _fixed_path(root: Path, key: str) -> Path:
    return base._repository_path(root, root / EVIDENCE_FILES[key][0], key)


def _authenticate_files(root: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = {}
    for key, (_, digest) in EVIDENCE_FILES.items():
        path = _fixed_path(root, key)
        if not path.is_file() or base._sha256(path) != digest:
            raise ValueError(f"evidence_identity:{key}")
        if path.suffix.lower() == ".json":
            loaded[key] = base._read_json(path, key)
    return loaded


def _git_value(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        raise ValueError("repository_git_identity")
    return completed.stdout.strip()


def _validate_p002_report(report: Mapping[str, Any], contract: Mapping[str, Any], declared: Mapping[str, str]) -> None:
    expected = list(contract["xml"]["titles"]) + list(contract["xml"].get("flash_handoffs") or [])
    overlays = report.get("overlay_evidence") or []
    snapshot = report.get("target_snapshot") or {}
    base_frame = snapshot.get("start_frame")
    zero = report.get("mutation_counts") or {}
    zero_expected = {
        "exports", "fusion_writes", "media_imports", "media_relinks", "media_replaces",
        "metadata_writes", "project_saves", "renders", "timeline_appends", "timeline_deletes",
        "timeline_imports", "timeline_selections", "title_writes",
    }
    strict = report.get("strict_validation") or {}
    structural = report.get("structural_validation") or {}
    structural_result = structural.get("result") or {}
    timelines = report.get("timeline_inventory_after") or []
    media = report.get("media_pool_inventory_after") or []
    targets = [row for row in timelines if row.get("name") == TARGET_NAME]
    gold = [row for row in timelines if row.get("name") == GOLD_NAME]
    if any((
        report.get("ok") is not True,
        report.get("task_id") != "VIDEO_CLONER_P002_LIVE_TARGET_FORENSIC_READBACK_V1",
        report.get("run_id") != P002_RUN_ID,
        report.get("mode") != "p002_readonly_existing_target_forensics",
        report.get("classification") != "DIRECT_TITLE_TEXT_UNOBSERVABLE_STRUCTURALLY_VALID",
        report.get("fallback_eligible") is not True,
        report.get("project_name") != PROJECT_NAME,
        report.get("target_timeline_name") != TARGET_NAME,
        report.get("target_unique_id") != TARGET_UID,
        report.get("overlay_mapping_exact") is not True,
        len(overlays) != len(expected) or len(expected) != 112,
        strict != {"failure": "ValueError: target_title", "ok": False, "result": None},
        structural.get("ok") is not True or structural.get("failure") is not None,
        structural_result.get("ok") is not True,
        structural_result.get("v1_clip_count") != 8,
        structural_result.get("a1_clip_count") != 1,
        structural_result.get("v2_title_count") != 112,
        structural_result.get("flash_handoff_count") != 0,
        structural_result.get("duration_frames") != 673,
        structural_result.get("snapshot") != snapshot,
        report.get("zero_mutation_claim") is not True,
        set(zero) != zero_expected or any(value != 0 for value in zero.values()),
        report.get("failures") != [],
        report.get("current_timeline_unchanged") is not True,
        report.get("timeline_inventory_unchanged") is not True,
        report.get("media_pool_inventory_unchanged") is not True,
        report.get("current_timeline_before") != report.get("current_timeline_after"),
        report.get("timeline_inventory_before") != timelines,
        report.get("media_pool_inventory_before") != media,
        len(timelines) != 46,
        len([row for row in timelines if row.get("name") != TARGET_NAME]) != 45,
        len(media) != 55,
        len(targets) != 1 or targets[0].get("unique_id") != TARGET_UID,
        len(gold) != 1 or gold[0].get("unique_id") != GOLD_UID,
        snapshot.get("name") != TARGET_NAME,
        snapshot.get("unique_id") != TARGET_UID,
        targets[0].get("signature") != snapshot.get("signature"),
        any(report.get(key) != value for key, value in declared.items()),
    )):
        raise ValueError("p002_accepted_state")
    for row, authority in zip(overlays, expected):
        start = base_frame + authority["timeline_start"] if isinstance(base_frame, int) else None
        if any((
            row.get("expected_text") != authority["text"],
            row.get("title_text") is not None,
            row.get("media_path") not in (None, ""),
            row.get("track") != authority["lane"] + 1,
            row.get("start") != start,
            row.get("end") != start + authority["duration"] if start is not None else True,
            row.get("duration") != authority["duration"],
            row.get("match_count") != 1,
        )):
            raise ValueError("p002_overlay_evidence")


def _accepted_evidence(root: Path, contract: Mapping[str, Any]) -> dict[str, Any]:
    files = _authenticate_files(root)
    declared = {key: contract[key] for key in ("artifact_set_sha256", "textplus_fingerprint", "fcpxml_sha256", "report_sha256")}
    p001_command = files["p001_command"]
    p001_report = files["p001_report"]
    p001_status = files["p001_status"]
    original = p001_command.get("payload") or {}
    if any((
        p001_command.get("task") != "VIDEO_CLONER_PHASE6_TEXTPLUS_APPLICATION_V1",
        p001_command.get("run_id") != P001_RUN_ID,
        p001_command.get("mode") != "phase6_import_textplus_full_fcpxml",
        original.get("expected_project") != PROJECT_NAME,
        original.get("target_timeline_name") != TARGET_NAME,
        original.get("require_target_absent") is not True,
        original.get("import_permitted") is not True,
        original.get("save_project") is not False,
        any(original.get(key) != value for key, value in declared.items()),
        p001_report.get("task_id") != p001_command.get("task"),
        p001_report.get("run_id") != P001_RUN_ID,
        p001_report.get("ok") is not False,
        p001_report.get("failures") != ["ValueError: target_title"],
        p001_report.get("import_call_count") != 1,
        p001_report.get("save_project_count") != 0,
        any(p001_report.get(key) != 0 for key in ("delete_call_count", "relink_call_count", "metadata_controller_call_count")),
        p001_status.get("run_id") != P001_RUN_ID,
        p001_status.get("running") is not False,
        p001_status.get("ok") is not False,
    )):
        raise ValueError("p001_accepted_state")

    p002_command = files["p002_command"]
    p002_status = files["p002_status"]
    diagnostic = p002_command.get("payload") or {}
    if any((
        p002_command.get("task") != "VIDEO_CLONER_P002_LIVE_TARGET_FORENSIC_READBACK_V1",
        p002_command.get("run_id") != P002_RUN_ID,
        p002_command.get("mode") != "p002_readonly_existing_target_forensics",
        p002_command.get("module") != "resolve_workspace/modules/video_cloner_p002_live_target_forensic_readback.py",
        diagnostic.get("p001_run_id") != P001_RUN_ID,
        diagnostic.get("expected_project") != PROJECT_NAME,
        diagnostic.get("target_timeline_name") != TARGET_NAME,
        diagnostic.get("read_only") is not True,
        diagnostic.get("zero_mutation") is not True,
        any(diagnostic.get(key) is not False for key in (
            "project_mutation_permitted", "timeline_mutation_permitted", "timeline_selection_permitted",
            "import_permitted", "save_project", "close_project_permitted", "delete_permitted",
            "rename_permitted", "append_permitted", "title_write_permitted", "fusion_write_permitted",
            "media_import_permitted", "relink_permitted", "replace_permitted", "export_permitted",
            "render_permitted", "metadata_write_permitted", "retry_permitted",
        )),
        any(diagnostic.get(key) != value for key, value in declared.items()),
        diagnostic.get("p001_command_sha256") != EVIDENCE_FILES["p001_command"][1],
        diagnostic.get("p001_bridge_report_sha256") != EVIDENCE_FILES["p001_report"][1],
        diagnostic.get("p001_status_sha256") != EVIDENCE_FILES["p001_status"][1],
        diagnostic.get("p001_t002_report_sha256") != EVIDENCE_FILES["p001_t002"][1],
        diagnostic.get("p001_preflight_evidence_sha256") != EVIDENCE_FILES["p001_preflight"][1],
        diagnostic.get("diagnostic_module_sha256") != EVIDENCE_FILES["p002_module"][1],
        p002_status.get("run_id") != P002_RUN_ID,
        p002_status.get("running") is not False,
        p002_status.get("ok") is not True,
    )):
        raise ValueError("p002_command_state")
    _validate_p002_report(files["p002_report"], contract, declared)
    return files["p002_report"]


def _semantic_acceptance(contract: Mapping[str, Any], validation: Mapping[str, Any], evidence: Mapping[str, Any]) -> dict[str, Any]:
    expected = list(contract["xml"]["titles"]) + list(contract["xml"].get("flash_handoffs") or [])
    snapshot = validation["snapshot"]
    base_frame = snapshot["start_frame"]
    caption_tracks = {row["lane"] + 1 for row in expected}
    actual = sorted(
        (row for row in snapshot["items"] if row["track_type"] == "video" and row["track_index"] in caption_tracks),
        key=lambda row: (row["track_index"], row["start"]),
    )
    authority = sorted(expected, key=lambda row: (row["lane"], row["timeline_start"]))
    if len(actual) != len(authority) or len(authority) != 112:
        raise ValueError("fallback_structural_identity")
    for row, expected_row in zip(actual, authority):
        if any((
            row["track_index"] != expected_row["lane"] + 1,
            row["start"] != base_frame + expected_row["timeline_start"],
            row["duration"] != expected_row["duration"],
            row.get("title_text") is not None,
            row.get("media_path") not in (None, ""),
        )):
            raise ValueError("fallback_semantic_contradiction")
    return {
        "policy": POLICY,
        "ok": True,
        "caption_count": len(authority),
        "direct_textplus_readback": "UNAVAILABLE",
        "p001_run_id": P001_RUN_ID,
        "p002_run_id": P002_RUN_ID,
        "p002_classification": evidence["classification"],
        "fallback_eligible": True,
    }


def _capture_state(project: Any, target_name: str, target_uid: str, contract: Mapping[str, Any]) -> dict[str, Any]:
    pool = base._safe(project, "GetMediaPool")
    if pool is None:
        raise ValueError("media_pool_missing")
    matches = _find(project, target_name)
    if len(matches) != 1 or base._unique_id(matches[0]) != target_uid:
        raise ValueError("target_identity")
    validation = base.validate_target(matches[0], contract["xml"], require_title_text=False)
    return {
        "current_timeline": _identity(base._safe(project, "GetCurrentTimeline")),
        "timeline_inventory": base._timeline_inventory(project),
        "media_pool_inventory": base._media_pool_inventory(pool),
        "target_validation": validation,
    }


def _require_baseline(state: Mapping[str, Any], evidence: Mapping[str, Any]) -> None:
    if state["current_timeline"] != evidence.get("current_timeline_after"):
        raise ValueError("current_timeline_drift")
    if _timeline_counter(state["timeline_inventory"]) != _timeline_counter(evidence.get("timeline_inventory_after") or []):
        raise ValueError("timeline_forensic_drift")
    if _media_counter(state["media_pool_inventory"]) != _media_counter(evidence.get("media_pool_inventory_after") or []):
        raise ValueError("media_forensic_drift")


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {
        "ok": False,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "classification": "P003_FALLBACK_SAVE_BLOCKED",
        "ownership_classification": None,
        "mutation_counts": {
            "timeline_imports": 0, "saves": 0, "timeline_selections": 0, "timeline_deletes": 0,
            "timeline_appends": 0, "title_writes": 0, "fusion_writes": 0, "media_imports": 0,
            "media_relinks": 0, "media_replaces": 0, "exports": 0, "renders": 0, "metadata_writes": 0,
        },
        "failures": [],
    }
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        required = {
            "action": ACTION,
            "save_once": True,
            "import_permitted": False,
            "save_project": True,
            "close_project_permitted": False,
            "timeline_selection_permitted": False,
            "delete_permitted": False,
            "rename_permitted": False,
            "append_permitted": False,
            "title_write_permitted": False,
            "fusion_write_permitted": False,
            "relink_permitted": False,
            "replace_permitted": False,
            "media_import_permitted": False,
            "export_permitted": False,
            "render_permitted": False,
            "metadata_write_permitted": False,
            "retry_permitted": False,
        }
        if command.get("task") != TASK_ID or command.get("run_id") != run_id or command.get("mode") != MODE or any(payload.get(k) != v for k, v in required.items()):
            raise ValueError("command_authority")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        if not (root / "AGENTS.md").is_file():
            raise ValueError("repository_identity")
        if _git_value(root, "branch", "--show-current") != "main" or _git_value(root, "rev-parse", "HEAD") != payload.get("expected_repository_head"):
            raise ValueError("repository_git_identity")
        if base._sha256(Path(__file__).resolve()) != payload.get("finalizer_module_sha256"):
            raise ValueError("finalizer_module_identity")
        manifest = _fixed_path(root, "manifest")
        if _preflight_path(root, payload.get("manifest_path")) != manifest or payload.get("manifest_sha256") != MANIFEST_SHA256:
            raise ValueError("manifest_identity")
        contract = base.load_phase5_contract(root, manifest)
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
        target_uid = str(payload.get("expected_target_uid") or "")
        if (project_name, target_name, target_uid) != (PROJECT_NAME, TARGET_NAME, TARGET_UID) or target_name != contract["xml"]["timeline_name"]:
            raise ValueError("target_authority")
        evidence = _accepted_evidence(root, contract)

        manager = base._safe(resolve, "GetProjectManager")
        project = base._safe(manager, "GetCurrentProject")
        if project is None or str(base._safe(project, "GetName", default="") or "") != project_name:
            raise ValueError("project_identity")
        before = _capture_state(project, target_name, target_uid, contract)
        _require_baseline(before, evidence)
        acceptance = _semantic_acceptance(contract, before["target_validation"], evidence)
        result["ownership_classification"] = "NEWLY_CREATED"
        result.update({"pre_save_state": before, "semantic_acceptance": acceptance, "protected_state_unchanged_pre_save": True})

        saved = base._safe(manager, "SaveProject", default=False)
        result["mutation_counts"]["saves"] = 1
        if saved is not True:
            raise ValueError("save_project")
        fresh_project = base._safe(base._safe(resolve, "GetProjectManager"), "GetCurrentProject")
        if fresh_project is None or str(base._safe(fresh_project, "GetName", default="") or "") != project_name:
            raise ValueError("post_save_project_identity")
        after = _capture_state(fresh_project, target_name, target_uid, contract)
        _require_baseline(after, evidence)
        post_save_acceptance = _semantic_acceptance(contract, after["target_validation"], evidence)
        if any((
            _timeline_counter(after["timeline_inventory"]) != _timeline_counter(before["timeline_inventory"]),
            _media_counter(after["media_pool_inventory"]) != _media_counter(before["media_pool_inventory"]),
            after["current_timeline"] != before["current_timeline"],
            after["target_validation"]["snapshot"]["signature"] != before["target_validation"]["snapshot"]["signature"],
        )):
            raise ValueError("post_save_state_drift")

        result.update({
            "ok": True,
            "classification": "P003_FALLBACK_SAVE_ACCEPTED",
            "project_name": project_name,
            "target_timeline_name": target_name,
            "target_unique_id": target_uid,
            "p001_run_id": P001_RUN_ID,
            "p002_run_id": P002_RUN_ID,
            "post_save_state": after,
            "post_save_semantic_acceptance": post_save_acceptance,
            "protected_state_unchanged": True,
            "save_succeeded": True,
            **declared,
        })
    except Exception as exc:
        result["failures"] = [f"{type(exc).__name__}: {exc}"]
    return result
