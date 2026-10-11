"""Import and retain the already-proven native boundary-80 transition DRT."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import zipfile
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


batch = _load("vc_oss003_persist_batch", HERE / "oss003_transition_representative_batch.py")
canary, rep = batch.canary, batch.rep

TASK_ID = "OSS003_NATIVE_B80_PERSIST_V1"
MODE = "oss003_native_b80_persist"
PROOF_NAME = "VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS003_NATIVE_B80"
PATCHED_RELATIVE = ".agent/reports/OSS003_NATIVE_BOUNDARY80_TRANSITION_V1/20261011T122841727Z_865b583a4be84ab69e7e9ab6955d0ce3/native_b80_patched.drt"
PATCHED_SHA256 = "785539a1761dd9e705abda2e93d722919d687b639647305b9602fd96cc10c694"
TOP_LEVEL_CONTAINER = "12d104aa-23eb-4780-bf08-f844b1cfa86b"
BOUNDARY = 80
DURATION = 11


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_patched_drt(path: Path) -> dict[str, Any]:
    if not path.is_file() or _sha256(path) != PATCHED_SHA256:
        raise ValueError("patched_drt_identity")
    with zipfile.ZipFile(path) as archive:
        xmls = {name: archive.read(name).decode("utf-8-sig") for name in archive.namelist() if name.lower().endswith(".xml")}
    entry = f"SeqContainer/{TOP_LEVEL_CONTAINER}.xml"
    if entry not in xmls:
        raise ValueError("top_level_container")
    transitions = [match.group(0) for xml in xmls.values() for match in re.finditer(r"<Sm2TiTransition\b[\s\S]*?</Sm2TiTransition>", xml)]
    if len(transitions) != 1 or transitions[0] not in xmls[entry]:
        raise ValueError(f"native_transition_count:{len(transitions)}")
    transition = transitions[0]
    start = int((re.search(r"<Start>(\d+)</Start>", transition) or [None, -1])[1])
    duration = int((re.search(r"<Duration>(\d+)</Duration>", transition) or [None, -1])[1])
    if "<PrettyType>Cross Dissolve</PrettyType>" not in transition or (start, duration) != (75, DURATION) or not start < BOUNDARY < start + duration:
        raise ValueError("native_transition_geometry")
    return {"sha256": PATCHED_SHA256, "entry": entry, "container_uuid": TOP_LEVEL_CONTAINER, "name": "Cross Dissolve", "start": start, "end": start + duration, "duration": duration, "cut": BOUNDARY, "count": 1}


def _find_optional(project: Any, name: str) -> Any:
    matches = [canary._optional(project, "GetTimelineByIndex", index) for index in range(1, int(canary._optional(project, "GetTimelineCount", default=0) or 0) + 1)]
    matches = [timeline for timeline in matches if timeline is not None and canary._name(timeline) == name]
    if len(matches) > 1:
        raise ValueError(f"timeline_name_ambiguous:{name}:{len(matches)}")
    return matches[0] if matches else None


def transition_readback(timeline: Any) -> dict[str, Any]:
    cut = int(canary._optional(timeline, "GetStartFrame", default=0) or 0) + BOUNDARY
    rows = []
    for item in canary._optional(timeline, "GetItemListInTrack", "video", 1, default=[]) or []:
        if canary._name(item) != "Cross Dissolve" or canary._optional(item, "GetMediaPoolItem") is not None:
            continue
        start = canary._item_start(item)
        end = canary._optional(item, "GetEnd", default=None)
        duration = canary._item_duration(item)
        properties = canary._optional(item, "GetProperty", default=None)
        if end is not None and duration == DURATION and start < cut < int(end) and not properties:
            rows.append({"name": "Cross Dissolve", "track": 1, "start": start, "end": int(end), "duration": duration, "cut": cut, "media_pool_item": None, "property": properties})
    if len(rows) != 1:
        raise RuntimeError(f"native_transition_readback:{len(rows)}")
    return rows[0]


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "mode": MODE, "run_id": run_id, "save_project_count": 0, "failures": []}
    project = imported = None
    imported_successfully = False
    try:
        command, payload = context.get("command") or {}, (context.get("command") or {}).get("payload") or {}
        required = {
            "expected_project": rep.EXPECTED_PROJECT, "production_timeline": rep.EXPECTED_TIMELINE,
            "production_uid": rep.EXPECTED_TIMELINE_UID, "proof_timeline": PROOF_NAME,
            "boundary_relative": BOUNDARY, "duration_frames": DURATION,
            "patched_drt_sha256": PATCHED_SHA256, "top_level_container": TOP_LEVEL_CONTAINER,
            "retain_after_import": True, "save_after_readback": True,
        }
        if command.get("task") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id or any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("command_authority")
        if _sha256(Path(__file__).resolve()) != payload.get("module_sha256"):
            raise ValueError("module_hash")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        patched = (root / PATCHED_RELATIVE).resolve()
        if not (root / "AGENTS.md").is_file() or Path(str(payload.get("patched_drt_path") or "")).resolve() != patched:
            raise ValueError("repository_or_patched_path")
        offline = validate_patched_drt(patched)
        if str(canary.carrier._call(resolve, "GetVersionString") or "") != rep.EXPECTED_RESOLVE_VERSION:
            raise ValueError("resolve_version")
        manager = canary.carrier._call(resolve, "GetProjectManager")
        project = canary.carrier._call(manager, "GetCurrentProject")
        if project is None or canary._name(project) != rep.EXPECTED_PROJECT:
            raise ValueError("project_identity")
        production = canary._find_timeline(project, rep.EXPECTED_TIMELINE)
        production_identity = canary._timeline_identity(production)
        if production_identity["unique_id"] != rep.EXPECTED_TIMELINE_UID:
            raise ValueError("production_uid")
        if _find_optional(project, PROOF_NAME) is not None:
            raise ValueError("proof_timeline_exists")
        pool = canary.carrier._call(project, "GetMediaPool")
        imported = canary._optional(pool, "ImportTimelineFromFile", str(patched), default=None)
        if imported is None:
            imported = _find_optional(project, PROOF_NAME)
        if imported is None or canary._name(imported) != PROOF_NAME:
            raise RuntimeError("patched_drt_import")
        imported_successfully = True
        proof_identity = canary._timeline_identity(imported)
        if not proof_identity["unique_id"] or proof_identity["unique_id"] == production_identity["unique_id"]:
            raise RuntimeError("proof_uid")
        if canary._optional(project, "SetCurrentTimeline", imported, default=False) is not True:
            raise RuntimeError("proof_activation")
        result.update({"patched_drt": offline, "production": {**production_identity, "untouched": True}, "proof": proof_identity, "proof_retained": True})
        live = transition_readback(imported)
        saved = canary._optional(manager, "SaveProject", default=False)
        result.update({"save_project_count": 1, "save_project_return": saved})
        if saved is not True:
            raise RuntimeError("save_project")
        current = canary._optional(project, "GetCurrentTimeline", default=None)
        if canary._timeline_identity(current) != proof_identity:
            raise RuntimeError("proof_not_current")
        result.update({"ok": True, "verification": "PASS", "live_transition": live, "current_timeline": proof_identity})
    except Exception as exc:
        result["failures"].append(f"{type(exc).__name__}: {exc}")
        if imported_successfully and project is not None and imported is not None:
            canary._optional(project, "SetCurrentTimeline", imported, default=False)
            result.update({
                "outcome": "OSS003_NATIVE_B80_IMPORTED_NEEDS_HUMAN_REVIEW",
                "proof": canary._timeline_identity(imported), "proof_retained": True,
                "current_timeline": canary._timeline_identity(canary._optional(project, "GetCurrentTimeline", default=None)),
            })
    return result


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1" and "resolve" in globals() and "context" in globals():
    result = run(resolve, context)
