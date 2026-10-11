"""Create one native Cross Dissolve proof timeline without touching production."""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


drt = _load("vc_oss003_native_drt", HERE / "oss003_native_transition_drt.py")
batch = _load("vc_oss003_native_batch", HERE / "oss003_transition_representative_batch.py")
canary, rep = batch.canary, batch.rep

TASK_ID = "OSS003_NATIVE_BOUNDARY80_TRANSITION_V1"
MODE = "oss003_native_boundary80_transition"
PROOF_NAME = "VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS003_NATIVE_B80"
SOURCE_COMMIT = "94c7a885d53f13be78522ce96561a9e9e21d64c5"
SOURCE_PATH = "resolve-advanced/vendor/drp-format/place-transition.js"
BOUNDARY = 80
DURATION = 11
PREFIX = "VC_OSS003_"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _items(timeline: Any, kind: str, track: int) -> list[Any]:
    return list(canary._optional(timeline, "GetItemListInTrack", kind, track, default=[]) or [])


def _pool_identity(item: Any) -> tuple[str, str]:
    pool_item = canary._optional(item, "GetMediaPoolItem")
    return canary._name(pool_item), str(canary._optional(pool_item, "GetUniqueId", default="") or "")


def _row(item: Any, *, include_fusion: bool = False) -> tuple[Any, ...]:
    enabled = canary._optional(item, "GetClipEnabled", default=None)
    row: tuple[Any, ...] = (canary._name(item), canary._item_start(item), canary._item_duration(item), enabled, *_pool_identity(item))
    if include_fusion:
        row += (tuple(canary._optional(item, "GetFusionCompNameList", default=[]) or []),)
    return row


def snapshot(timeline: Any, *, include_fusion: bool = False) -> dict[str, Any]:
    return {
        "identity": canary._timeline_identity(timeline),
        "base": int(canary._optional(timeline, "GetStartFrame", default=0) or 0),
        "video_tracks": int(canary._optional(timeline, "GetTrackCount", "video", default=0) or 0),
        "audio_tracks": int(canary._optional(timeline, "GetTrackCount", "audio", default=0) or 0),
        "v1": [_row(item, include_fusion=include_fusion) for item in _items(timeline, "video", 1) if canary._optional(item, "GetMediaPoolItem") is not None],
        "v2": [_row(item) for item in _items(timeline, "video", 2)],
        "v3": [_row(item) for item in _items(timeline, "video", 3)],
        "a1": [_row(item) for item in _items(timeline, "audio", 1)],
    }


def preservation_view(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in ("base", "video_tracks", "audio_tracks", "v1", "v2", "v3", "a1")}


def handle_preflight(v1: list[Any]) -> dict[str, Any]:
    if len(v1) != 8:
        raise ValueError(f"v1_media_count:{len(v1)}")
    outgoing, incoming = v1[0], v1[1]
    available_outgoing = int(canary._optional(outgoing, "GetRightOffset", default=-1) or 0)
    available_incoming = int(canary._optional(incoming, "GetLeftOffset", default=-1) or 0)
    result = {
        "outgoing_right_available": available_outgoing, "outgoing_right_required": 6,
        "incoming_left_available": available_incoming, "incoming_left_required": 5,
    }
    if available_outgoing < 6 or available_incoming < 5:
        raise ValueError(f"insufficient_handles:outgoing={available_outgoing}/6:incoming={available_incoming}/5")
    return result


def transition_readback(timeline: Any, absolute_cut: int) -> dict[str, Any]:
    rows = []
    for item in _items(timeline, "video", 1):
        props = canary._optional(item, "GetProperty", default=None)
        if canary._name(item) == "Cross Dissolve" and canary._optional(item, "GetMediaPoolItem") is None and props == {}:
            start, duration = canary._item_start(item), canary._item_duration(item)
            end = canary._optional(item, "GetEnd", default=None)
            if end is None:
                raise RuntimeError("native_transition_end_readback")
            rows.append({"item": item, "name": canary._name(item), "track": 1, "start": start, "end": int(end), "duration": duration, "media_pool_item": None, "property": props})
    if len(rows) != 1:
        raise RuntimeError(f"native_transition_count:{len(rows)}")
    row = rows[0]
    if row["duration"] != DURATION or row["end"] - row["start"] != DURATION or not row["start"] < absolute_cut < row["end"]:
        raise RuntimeError(f"native_transition_geometry:{row['start']}:{row['end']}:{absolute_cut}")
    return {key: value for key, value in row.items() if key != "item"}


def remove_experimental_fusion(timeline: Any) -> list[dict[str, Any]]:
    removed = []
    for item in _items(timeline, "video", 1):
        for name in list(canary._optional(item, "GetFusionCompNameList", default=[]) or []):
            if str(name).startswith(PREFIX):
                if canary._optional(item, "DeleteFusionCompByName", name, default=False) is not True:
                    raise RuntimeError(f"fusion_cleanup:{name}")
                removed.append({"clip": canary._name(item), "comp": str(name)})
    remaining = [str(name) for item in _items(timeline, "video", 1) for name in (canary._optional(item, "GetFusionCompNameList", default=[]) or []) if str(name).startswith(PREFIX)]
    if remaining:
        raise RuntimeError(f"fusion_cleanup_readback:{remaining!r}")
    return removed


def _find_optional(project: Any, name: str) -> Any:
    matches = [canary._optional(project, "GetTimelineByIndex", index) for index in range(1, int(canary._optional(project, "GetTimelineCount", default=0) or 0) + 1)]
    matches = [timeline for timeline in matches if timeline is not None and canary._name(timeline) == name]
    if len(matches) > 1:
        raise ValueError(f"timeline_name_ambiguous:{name}:{len(matches)}")
    return matches[0] if matches else None


def _delete_exact(project: Any, pool: Any, timeline: Any, uid: str) -> bool:
    if timeline is None or canary._timeline_identity(timeline)["unique_id"] != uid:
        return False
    if canary._optional(pool, "DeleteTimelines", [timeline], default=False) is not True:
        return False
    return all(canary._timeline_identity(canary._optional(project, "GetTimelineByIndex", index))["unique_id"] != uid for index in range(1, int(canary._optional(project, "GetTimelineCount", default=0) or 0) + 1))


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "mode": MODE, "run_id": run_id, "save_project_count": 0, "failures": [], "warning": "clip-level Fusion transition route rejected for OSS-003"}
    project = pool = production = temporary = imported = None
    temporary_uid = imported_uid = ""
    try:
        command, payload = context.get("command") or {}, (context.get("command") or {}).get("payload") or {}
        required = {
            "expected_project": rep.EXPECTED_PROJECT, "production_timeline": rep.EXPECTED_TIMELINE,
            "production_uid": rep.EXPECTED_TIMELINE_UID, "proof_timeline": PROOF_NAME,
            "boundary_relative": BOUNDARY, "track": 1, "duration_frames": DURATION,
            "transition_type": "dissolve", "oss_commit": SOURCE_COMMIT, "oss_path": SOURCE_PATH,
            "save_after_verification": True,
        }
        if command.get("task") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id or any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("command_authority")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        if _sha256(Path(__file__).resolve()) != payload.get("module_sha256") or _sha256(HERE / "oss003_native_transition_drt.py") != payload.get("drt_module_sha256"):
            raise ValueError("module_hash")
        version = str(canary.carrier._call(resolve, "GetVersionString") or "")
        if version != rep.EXPECTED_RESOLVE_VERSION:
            raise ValueError(f"resolve_version:{version}")
        manager = canary.carrier._call(resolve, "GetProjectManager")
        project = canary.carrier._call(manager, "GetCurrentProject")
        if project is None or canary._name(project) != rep.EXPECTED_PROJECT:
            raise ValueError("project_identity")
        pool = canary.carrier._call(project, "GetMediaPool")
        production = canary._find_timeline(project, rep.EXPECTED_TIMELINE)
        if canary._timeline_identity(production)["unique_id"] != rep.EXPECTED_TIMELINE_UID:
            raise ValueError("production_uid")
        if _find_optional(project, PROOF_NAME) is not None:
            raise ValueError("proof_timeline_exists")
        if canary._optional(project, "SetCurrentTimeline", production, default=False) is not True:
            raise RuntimeError("production_activation")
        before = snapshot(production, include_fusion=True)
        if before["video_tracks"] != 3 or len(before["v1"]) != 8 or len(before["v2"]) != 112 or len(before["v3"]) != 69:
            raise ValueError(f"production_baseline:v={before['video_tracks']}:v1={len(before['v1'])}:v2={len(before['v2'])}:v3={len(before['v3'])}")
        absolute_cut = before["base"] + BOUNDARY
        v1_items = [item for item in _items(production, "video", 1) if canary._optional(item, "GetMediaPoolItem") is not None]
        if [(canary._item_start(item) - before["base"], canary._item_duration(item)) for item in v1_items] != list(batch.EXPECTED_V1):
            raise ValueError("v1_boundary_contract")
        handles = handle_preflight(v1_items)
        temporary = canary._optional(production, "DuplicateTimeline", PROOF_NAME, default=None)
        if temporary is None or canary._name(temporary) != PROOF_NAME:
            raise RuntimeError("duplicate_timeline")
        temporary_uid = canary._timeline_identity(temporary)["unique_id"]
        if not temporary_uid or temporary_uid == rep.EXPECTED_TIMELINE_UID:
            raise RuntimeError("duplicate_uid")
        report_dir = root / str(command["report_path"]).replace("/report.json", "")
        source_drt, patched_drt = report_dir / "source_unpatched.drt", report_dir / "native_b80_patched.drt"
        report_dir.mkdir(parents=True, exist_ok=True)
        export_type = getattr(resolve, "EXPORT_DRT", None)
        if export_type is None or canary._optional(temporary, "Export", str(source_drt), export_type, default=False) is not True or not source_drt.is_file():
            raise RuntimeError("drt_export")
        sequence = drt.select_top_level(source_drt, PROOF_NAME)
        offline = drt.place_transition(source_drt, patched_drt, timeline_name=PROOF_NAME, timeline_uuid=sequence["id"], track=1, at_frame=absolute_cut, duration_frames=DURATION)
        if canary._optional(project, "SetCurrentTimeline", production, default=False) is not True or not _delete_exact(project, pool, temporary, temporary_uid):
            raise RuntimeError("temporary_duplicate_delete")
        temporary = None
        imported = canary._optional(pool, "ImportTimelineFromFile", str(patched_drt), default=None)
        if imported is None:
            imported = _find_optional(project, PROOF_NAME)
        if imported is None or canary._name(imported) != PROOF_NAME:
            raise RuntimeError("patched_drt_import")
        imported_uid = canary._timeline_identity(imported)["unique_id"]
        if not imported_uid or imported_uid == rep.EXPECTED_TIMELINE_UID or canary._optional(project, "SetCurrentTimeline", imported, default=False) is not True:
            raise RuntimeError("imported_identity")
        removed = remove_experimental_fusion(imported)
        transition = transition_readback(imported, absolute_cut)
        proof = snapshot(imported)
        baseline_core = {**before, "v1": [row[:-1] for row in before["v1"]]}
        if preservation_view(proof) != preservation_view(baseline_core):
            raise RuntimeError("proof_timeline_preservation")
        if canary._optional(project, "SetCurrentTimeline", production, default=False) is not True or snapshot(production, include_fusion=True) != before:
            raise RuntimeError("production_changed")
        if canary._optional(project, "SetCurrentTimeline", imported, default=False) is not True:
            raise RuntimeError("proof_reactivation")
        saved = canary._optional(manager, "SaveProject", default=False)
        result.update({"save_project_count": 1, "save_project_return": saved})
        if saved is not True:
            raise RuntimeError("save_project")
        result.update({
            "ok": True, "verification": "PASS", "resolve_version": version,
            "production": before["identity"], "proof": proof["identity"], "absolute_cut": absolute_cut,
            "handles": handles, "top_level_sequence": sequence, "offline_drt": offline,
            "live_transition": transition, "fusion_cleanup": {"removed": removed, "remaining_owned": 0},
            "preservation": {"v1_media": len(proof["v1"]), "v2": len(proof["v2"]), "v3": len(proof["v3"]), "a1": len(proof["a1"]), "production_untouched": True},
            "current_timeline": proof["identity"],
        })
    except Exception as exc:
        result["failures"].append(f"{type(exc).__name__}: {exc}")
        if project is not None and pool is not None and production is not None:
            canary._optional(project, "SetCurrentTimeline", production, default=False)
            cleanup = []
            for candidate, uid, label in ((imported, imported_uid, "imported_proof"), (temporary, temporary_uid, "temporary_duplicate")):
                if candidate is not None and uid:
                    cleanup.append({"timeline": label, "uid": uid, "deleted": _delete_exact(project, pool, candidate, uid)})
            result["failure_cleanup"] = cleanup
    return result


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1" and "resolve" in globals() and "context" in globals():
    result = run(resolve, context)
