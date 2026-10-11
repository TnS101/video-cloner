"""Import the final Reel #3 derivative with three donor-native Blur Dissolves."""
from __future__ import annotations

import hashlib
import importlib.util
import json
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


blur = _load("vc_oss003_final_blur", HERE / "oss003_native_blur_drt.py")
batch = _load("vc_oss003_final_batch", HERE / "oss003_transition_representative_batch.py")
canary, rep = batch.canary, batch.rep

TASK_ID = "OSS003_FINAL_TRANSITION_ROLLOUT_V1"
MODE = "oss003_final_transition_rollout"
FINAL_NAME = "VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS003_TRANSITIONS_V1"
BOUNDARIES = ((80, 11), (286, 11), (376, 11))
TEMPLATE_SHA256 = "2b57d7e86794046bb72b32d0e76ac0ddc791c661a0ee88af6d6352ace3bdc326"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _find_optional(project: Any, name: str) -> Any:
    rows = [canary._optional(project, "GetTimelineByIndex", index) for index in range(1, int(canary._optional(project, "GetTimelineCount", default=0) or 0) + 1)]
    matches = [row for row in rows if row is not None and canary._name(row) == name]
    if len(matches) > 1:
        raise ValueError(f"timeline_name_ambiguous:{name}:{len(matches)}")
    return matches[0] if matches else None


def _delete_exact(project: Any, pool: Any, timeline: Any, uid: str) -> bool:
    return bool(timeline is not None and canary._timeline_identity(timeline)["unique_id"] == uid and canary._optional(pool, "DeleteTimelines", [timeline], default=False) is True)


def _item_tuple(item: Any) -> tuple[Any, ...]:
    pool_item = canary._optional(item, "GetMediaPoolItem")
    enabled = canary._optional(item, "GetClipEnabled", default=None)
    return (canary._name(item), canary._item_start(item), canary._item_duration(item), enabled, canary._name(pool_item) if pool_item is not None else "")


def _compact_snapshot(timeline: Any) -> dict[str, Any]:
    base_frame = int(canary._optional(timeline, "GetStartFrame", default=0) or 0)
    groups: dict[str, list[tuple[Any, ...]]] = {}
    for track_type, tracks in (("video", (1, 2, 3)), ("audio", (1,))):
        for track in tracks:
            rows = []
            for item in canary._optional(timeline, "GetItemListInTrack", track_type, track, default=[]) or []:
                if track_type == "video" and track == 1 and canary._optional(item, "GetMediaPoolItem") is None:
                    continue
                row = list(_item_tuple(item))
                row[1] -= base_frame
                rows.append(tuple(row))
            groups[f"{track_type[0].upper()}{track}"] = sorted(rows, key=lambda row: (row[1], row[2], row[0]))
    counts = {key: len(value) for key, value in groups.items()}
    if counts["V1"] != 8 or counts["V2"] != 112 or counts["V3"] != 69 or counts["A1"] == 0:
        raise ValueError(f"production_inventory:{counts}")
    return {"counts": counts, "hashes": {key: hashlib.sha256(json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest() for key, value in groups.items()}}


def _preflight(production: Any) -> dict[str, Any]:
    base_frame = int(canary._optional(production, "GetStartFrame", default=0) or 0)
    items = [item for item in (canary._optional(production, "GetItemListInTrack", "video", 1, default=[]) or []) if canary._optional(item, "GetMediaPoolItem") is not None]
    placements = tuple((canary._item_start(item) - base_frame, canary._item_duration(item)) for item in items)
    if placements != batch.EXPECTED_V1:
        raise ValueError(f"v1_contract:{placements!r}")
    handles = []
    for cut, _ in BOUNDARIES:
        index = next((i for i in range(len(items) - 1) if placements[i][0] + placements[i][1] == placements[i + 1][0] == cut), -1)
        outgoing = int(canary._optional(items[index], "GetRightOffset", default=-1) or 0) if index >= 0 else -1
        incoming = int(canary._optional(items[index + 1], "GetLeftOffset", default=-1) or 0) if index >= 0 else -1
        if index < 0 or outgoing < 6 or incoming < 5:
            raise ValueError(f"insufficient_handles:{cut}:{outgoing}:{incoming}")
        handles.append({"cut": cut, "outgoing_right": outgoing, "incoming_left": incoming})
    return {"base_frame": base_frame, "placements": placements, "handles": handles}


def _live_transitions(timeline: Any) -> list[dict[str, Any]]:
    base_frame = int(canary._optional(timeline, "GetStartFrame", default=0) or 0)
    rows = []
    for item in canary._optional(timeline, "GetItemListInTrack", "video", 1, default=[]) or []:
        if canary._optional(item, "GetMediaPoolItem") is not None:
            continue
        start, end, duration = canary._item_start(item), int(canary._optional(item, "GetEnd", default=-1) or -1), canary._item_duration(item)
        rows.append({"name": canary._name(item), "track": 1, "start": start, "end": end, "duration": duration})
    if len(rows) != len(BOUNDARIES) or any(row["name"] != "Blur Dissolve" or row["duration"] != 11 for row in rows):
        raise RuntimeError(f"native_transition_count_or_type:{rows!r}")
    for cut, duration in BOUNDARIES:
        absolute = base_frame + cut
        matches = [row for row in rows if row["duration"] == duration and row["start"] < absolute < row["end"]]
        if len(matches) != 1:
            raise RuntimeError(f"native_transition_geometry:{cut}:{matches!r}")
        matches[0]["cut_relative"] = cut
    return sorted(rows, key=lambda row: row["start"])


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "mode": MODE, "run_id": run_id, "save_project_count": 0, "failures": []}
    project = pool = production = temporary = imported = None
    temporary_uid = ""
    imported_successfully = False
    try:
        command, payload = context.get("command") or {}, (context.get("command") or {}).get("payload") or {}
        required = {
            "expected_project": rep.EXPECTED_PROJECT, "production_timeline": rep.EXPECTED_TIMELINE,
            "production_uid": rep.EXPECTED_TIMELINE_UID, "final_timeline": FINAL_NAME,
            "boundaries": [{"relative_frame": cut, "duration_frames": duration, "type": "Blur Dissolve"} for cut, duration in BOUNDARIES],
            "retain_after_import": True, "save_after_readback": True, "fusion_debt_policy": "defer_nonblocking",
        }
        if command.get("task") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id or any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("command_authority")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        template_path = Path(str(payload.get("donor_template_path") or "")).resolve()
        template_path.relative_to(root)
        if not (root / "AGENTS.md").is_file() or _sha256(Path(__file__).resolve()) != payload.get("module_sha256") or _sha256(HERE / "oss003_native_blur_drt.py") != payload.get("drt_module_sha256"):
            raise ValueError("module_identity")
        if not template_path.is_file() or _sha256(template_path) != TEMPLATE_SHA256 or payload.get("donor_template_sha256") != TEMPLATE_SHA256:
            raise ValueError("donor_template_identity")
        result["resolve_version"] = str(canary.carrier._call(resolve, "GetVersionString") or "")
        if result["resolve_version"] != rep.EXPECTED_RESOLVE_VERSION:
            raise ValueError("resolve_version")
        manager = canary.carrier._call(resolve, "GetProjectManager")
        project = canary.carrier._call(manager, "GetCurrentProject")
        if project is None or canary._name(project) != rep.EXPECTED_PROJECT:
            raise ValueError("project_identity")
        production = canary._find_timeline(project, rep.EXPECTED_TIMELINE)
        if canary._timeline_identity(production)["unique_id"] != rep.EXPECTED_TIMELINE_UID:
            raise ValueError("production_uid")
        if _find_optional(project, FINAL_NAME) is not None:
            raise ValueError("final_timeline_exists")
        pool = canary.carrier._call(project, "GetMediaPool")
        preflight, production_before = _preflight(production), _compact_snapshot(production)
        report_dir = root / str(command["report_path"]).replace("/report.json", "")
        report_dir.mkdir(parents=True, exist_ok=True)
        temporary = canary._optional(production, "DuplicateTimeline", FINAL_NAME, default=None)
        if temporary is None or canary._name(temporary) != FINAL_NAME:
            raise RuntimeError("duplicate_timeline")
        temporary_uid = canary._timeline_identity(temporary)["unique_id"]
        export_type = getattr(resolve, "EXPORT_DRT", None)
        unpatched = report_dir / "final_unpatched.drt"
        if export_type is None or canary._optional(temporary, "Export", str(unpatched), export_type, default=False) is not True:
            raise RuntimeError("final_drt_export")
        target = blur.base.select_top_level(unpatched, FINAL_NAME)
        patched = report_dir / "final_transitions_v1.drt"
        absolute = [(preflight["base_frame"] + cut, duration) for cut, duration in BOUNDARIES]
        offline = blur.place_blur_transitions(unpatched, patched, timeline_name=FINAL_NAME, timeline_uuid=target["id"], donor_element=template_path.read_text(encoding="utf-8-sig"), track=1, boundaries=absolute)
        if canary._optional(project, "SetCurrentTimeline", production, default=False) is not True or not _delete_exact(project, pool, temporary, temporary_uid):
            raise RuntimeError("temporary_duplicate_cleanup")
        temporary = None
        imported = canary._optional(pool, "ImportTimelineFromFile", str(patched), default=None) or _find_optional(project, FINAL_NAME)
        if imported is None or canary._name(imported) != FINAL_NAME:
            raise RuntimeError("final_import")
        imported_successfully = True
        final_identity = canary._timeline_identity(imported)
        if not final_identity["unique_id"] or canary._optional(project, "SetCurrentTimeline", imported, default=False) is not True:
            raise RuntimeError("final_activation")
        live = _live_transitions(imported)
        final_snapshot = _compact_snapshot(imported)
        if final_snapshot != production_before:
            raise RuntimeError("final_preservation")
        production_after = _compact_snapshot(production)
        if production_after != production_before:
            raise RuntimeError("production_mutated")
        if canary._optional(project, "SetCurrentTimeline", imported, default=False) is not True:
            raise RuntimeError("final_reactivation")
        saved = canary._optional(manager, "SaveProject", default=False)
        result.update({"save_project_count": 1, "save_project_return": saved})
        if saved is not True:
            raise RuntimeError("save_project")
        if canary._timeline_identity(canary._optional(project, "GetCurrentTimeline", default=None)) != final_identity:
            raise RuntimeError("final_not_current")
        result.update({
            "ok": True, "verification": "PASS", "preflight": preflight, "offline": offline,
            "live_transitions": live, "production": {**canary._timeline_identity(production), "untouched": True},
            "final": final_identity, "final_retained": True, "current_timeline": final_identity,
            "preservation": final_snapshot, "fusion_debt": {"policy": "deferred", "blocking": False, "mutation": "none"},
            "slide_classification": {"211": "CLIP_MOTION_VFX_DEFER_OSS004", "629": "CLIP_MOTION_VFX_DEFER_OSS004"},
            "whip_461": "DEFER_OSS004", "patched_drt_sha256": _sha256(patched),
        })
    except Exception as exc:
        result["failures"].append(f"{type(exc).__name__}: {exc}")
        if imported_successfully and project is not None and imported is not None:
            canary._optional(project, "SetCurrentTimeline", imported, default=False)
            result.update({"outcome": "OSS003_FINAL_IMPORTED_RETAINED_NEEDS_HUMAN_REVIEW", "final": canary._timeline_identity(imported), "final_retained": True})
        elif project is not None and pool is not None and temporary is not None and temporary_uid:
            if production is not None:
                canary._optional(project, "SetCurrentTimeline", production, default=False)
            result["temporary_cleanup"] = _delete_exact(project, pool, temporary, temporary_uid)
    return result


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1" and "resolve" in globals() and "context" in globals():
    result = run(resolve, context)
