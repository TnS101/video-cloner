"""Harvest the human-authored Blur Dissolve and apply one automated B80 proof."""
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


blur_drt = _load("vc_oss003_blur_drt", HERE / "oss003_native_blur_drt.py")
batch = _load("vc_oss003_blur_batch", HERE / "oss003_transition_representative_batch.py")
canary, rep = batch.canary, batch.rep

TASK_ID = "OSS003_NATIVE_BLUR_AUTO_B80_V1"
MODE = "oss003_native_blur_auto_b80"
DONOR_NAME = "VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS003_NATIVE_B80"
DONOR_UID = "3914da03-c195-4cd7-9a59-c4537b532138"
PROOF_NAME = "VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS003_BLUR_AUTO_B80"
CROSS_SHA256 = "785539a1761dd9e705abda2e93d722919d687b639647305b9602fd96cc10c694"
BOUNDARY = 80
DURATION = 11


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _find_optional(project: Any, name: str) -> Any:
    rows = [canary._optional(project, "GetTimelineByIndex", index) for index in range(1, int(canary._optional(project, "GetTimelineCount", default=0) or 0) + 1)]
    matches = [row for row in rows if row is not None and canary._name(row) == name]
    if len(matches) > 1:
        raise ValueError(f"timeline_name_ambiguous:{name}:{len(matches)}")
    return matches[0] if matches else None


def _delete_exact(project: Any, pool: Any, timeline: Any, uid: str) -> bool:
    if timeline is None or canary._timeline_identity(timeline)["unique_id"] != uid:
        return False
    return canary._optional(pool, "DeleteTimelines", [timeline], default=False) is True


def _handle_preflight(production: Any) -> dict[str, int]:
    items = [item for item in (canary._optional(production, "GetItemListInTrack", "video", 1, default=[]) or []) if canary._optional(item, "GetMediaPoolItem") is not None]
    if len(items) != 8:
        raise ValueError(f"v1_media_count:{len(items)}")
    outgoing = int(canary._optional(items[0], "GetRightOffset", default=-1) or 0)
    incoming = int(canary._optional(items[1], "GetLeftOffset", default=-1) or 0)
    if outgoing < 6 or incoming < 5:
        raise ValueError(f"insufficient_handles:{outgoing}:{incoming}")
    return {"outgoing_right": outgoing, "incoming_left": incoming}


def _live_transition(timeline: Any) -> dict[str, Any]:
    cut = int(canary._optional(timeline, "GetStartFrame", default=0) or 0) + BOUNDARY
    rows = []
    for item in canary._optional(timeline, "GetItemListInTrack", "video", 1, default=[]) or []:
        if canary._name(item) != "Blur Dissolve" or canary._optional(item, "GetMediaPoolItem") is not None:
            continue
        start, end, duration = canary._item_start(item), canary._optional(item, "GetEnd", default=None), canary._item_duration(item)
        properties = canary._optional(item, "GetProperty", default=None)
        if end is not None and duration == DURATION and start < cut < int(end) and not properties:
            rows.append({"name": "Blur Dissolve", "track": 1, "start": start, "end": int(end), "duration": duration, "cut": cut, "media_pool_item": None, "property": properties})
    if len(rows) != 1:
        raise RuntimeError(f"blur_transition_readback:{len(rows)}")
    return rows[0]


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "mode": MODE, "run_id": run_id, "save_project_count": 0, "failures": []}
    project = pool = donor = production = temporary = imported = None
    temporary_uid = ""
    imported_successfully = False
    try:
        command, payload = context.get("command") or {}, (context.get("command") or {}).get("payload") or {}
        required = {
            "expected_project": rep.EXPECTED_PROJECT, "production_timeline": rep.EXPECTED_TIMELINE,
            "production_uid": rep.EXPECTED_TIMELINE_UID, "donor_timeline": DONOR_NAME, "donor_uid": DONOR_UID,
            "proof_timeline": PROOF_NAME, "boundary_relative": BOUNDARY, "duration_frames": DURATION,
            "transition_type": "blur-dissolve", "retain_after_import": True, "save_after_readback": True,
        }
        if command.get("task") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id or any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("command_authority")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        if not (root / "AGENTS.md").is_file() or _sha256(Path(__file__).resolve()) != payload.get("module_sha256") or _sha256(HERE / "oss003_native_blur_drt.py") != payload.get("drt_module_sha256"):
            raise ValueError("module_identity")
        cross_path = Path(str(payload.get("cross_drt_path") or "")).resolve()
        if not cross_path.is_file() or _sha256(cross_path) != CROSS_SHA256:
            raise ValueError("cross_drt_identity")
        if str(canary.carrier._call(resolve, "GetVersionString") or "") != rep.EXPECTED_RESOLVE_VERSION:
            raise ValueError("resolve_version")
        manager = canary.carrier._call(resolve, "GetProjectManager")
        project = canary.carrier._call(manager, "GetCurrentProject")
        if project is None or canary._name(project) != rep.EXPECTED_PROJECT:
            raise ValueError("project_identity")
        donor, production = canary._find_timeline(project, DONOR_NAME), canary._find_timeline(project, rep.EXPECTED_TIMELINE)
        if canary._timeline_identity(donor)["unique_id"] != DONOR_UID or canary._timeline_identity(production)["unique_id"] != rep.EXPECTED_TIMELINE_UID:
            raise ValueError("timeline_uid")
        if canary._timeline_identity(canary._optional(project, "GetCurrentTimeline", default=None)) != canary._timeline_identity(donor):
            raise ValueError("donor_not_current")
        if _find_optional(project, PROOF_NAME) is not None:
            raise ValueError("proof_timeline_exists")
        pool = canary.carrier._call(project, "GetMediaPool")
        handles = _handle_preflight(production)
        report_dir = root / str(command["report_path"]).replace("/report.json", "")
        report_dir.mkdir(parents=True, exist_ok=True)
        donor_path = report_dir / "blur_donor.drt"
        export_type = getattr(resolve, "EXPORT_DRT", None)
        if export_type is None or canary._optional(donor, "Export", str(donor_path), export_type, default=False) is not True:
            raise RuntimeError("blur_donor_export")
        donor_hash = _sha256(donor_path)
        donor_transition = blur_drt.extract_transition(donor_path, DONOR_NAME)
        if donor_transition["pretty_type"] != "Blur Dissolve" or donor_transition["duration"] != DURATION or donor_transition["start"] != 75:
            raise ValueError("blur_donor_contract")
        cross_transition = blur_drt.extract_transition(cross_path, DONOR_NAME)
        structural_diff = blur_drt.transition_diff(cross_transition, donor_transition)
        template_path = report_dir / "blur_dissolve_template.xml"
        template_path.write_text(donor_transition["element"] + "\n", encoding="utf-8")
        temporary = canary._optional(production, "DuplicateTimeline", PROOF_NAME, default=None)
        if temporary is None or canary._name(temporary) != PROOF_NAME:
            raise RuntimeError("duplicate_timeline")
        temporary_uid = canary._timeline_identity(temporary)["unique_id"]
        unpatched = report_dir / "fresh_unpatched.drt"
        if canary._optional(temporary, "Export", str(unpatched), export_type, default=False) is not True:
            raise RuntimeError("fresh_drt_export")
        target = blur_drt.base.select_top_level(unpatched, PROOF_NAME)
        patched = report_dir / "blur_auto_b80.drt"
        absolute_cut = int(canary._optional(production, "GetStartFrame", default=0) or 0) + BOUNDARY
        offline = blur_drt.place_blur_transition(unpatched, patched, timeline_name=PROOF_NAME, timeline_uuid=target["id"], donor_element=donor_transition["element"], track=1, at_frame=absolute_cut, duration_frames=DURATION)
        if canary._optional(project, "SetCurrentTimeline", donor, default=False) is not True or not _delete_exact(project, pool, temporary, temporary_uid):
            raise RuntimeError("temporary_duplicate_cleanup")
        temporary = None
        imported = canary._optional(pool, "ImportTimelineFromFile", str(patched), default=None) or _find_optional(project, PROOF_NAME)
        if imported is None or canary._name(imported) != PROOF_NAME:
            raise RuntimeError("blur_proof_import")
        imported_successfully = True
        proof_identity = canary._timeline_identity(imported)
        if not proof_identity["unique_id"] or canary._optional(project, "SetCurrentTimeline", imported, default=False) is not True:
            raise RuntimeError("blur_proof_activation")
        result.update({
            "donor_harvest": {"drt_sha256": donor_hash, "container_uuid": donor_transition["container_uuid"], "transition": {key: donor_transition["fields"].get(key) for key in ("PrettyType", "Start", "Duration", "AlignmentType", "Position", "FieldsBlob", "EffectFiltersBA")}, "diff": structural_diff, "template_path": str(template_path)},
            "automation": {"offline": offline, "patched_drt_sha256": _sha256(patched)},
            "production": {**canary._timeline_identity(production), "untouched": True}, "proof": proof_identity,
            "proof_retained": True, "handles": handles,
        })
        live = _live_transition(imported)
        saved = canary._optional(manager, "SaveProject", default=False)
        result.update({"save_project_count": 1, "save_project_return": saved})
        if saved is not True:
            raise RuntimeError("save_project")
        if canary._timeline_identity(canary._optional(project, "GetCurrentTimeline", default=None)) != proof_identity:
            raise RuntimeError("proof_not_current")
        result.update({"ok": True, "verification": "PASS", "live_transition": live, "current_timeline": proof_identity})
    except Exception as exc:
        result["failures"].append(f"{type(exc).__name__}: {exc}")
        if imported_successfully and project is not None and imported is not None:
            canary._optional(project, "SetCurrentTimeline", imported, default=False)
            result.update({"outcome": "OSS003_NATIVE_BLUR_B80_IMPORTED_NEEDS_HUMAN_REVIEW", "proof": canary._timeline_identity(imported), "proof_retained": True, "current_timeline": canary._timeline_identity(canary._optional(project, "GetCurrentTimeline", default=None))})
        elif project is not None and pool is not None and temporary is not None and temporary_uid:
            if donor is not None:
                canary._optional(project, "SetCurrentTimeline", donor, default=False)
            result["temporary_cleanup"] = _delete_exact(project, pool, temporary, temporary_uid)
    return result


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1" and "resolve" in globals() and "context" in globals():
    result = run(resolve, context)
