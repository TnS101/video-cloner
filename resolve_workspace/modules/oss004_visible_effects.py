"""Add the missing native Push and one source-backed shake to Reel #3."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import uuid
import xml.etree.ElementTree as ET
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


batch = _load("vc_oss004_visible_batch", HERE / "oss003_transition_representative_batch.py")
base = _load("vc_oss004_visible_drt", HERE / "oss003_native_transition_drt.py")
repair = _load("vc_oss004_visible_fusion", HERE / "oss003_blur_boundary80_repair.py")
canary, rep, fusion = batch.canary, batch.rep, repair.fusion

TASK_ID = "OSS004_VISIBLE_EFFECTS_V1"
MODE = "oss004_visible_effects"
BASELINE_NAME = "VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS003_TRANSITIONS_V1"
BASELINE_UID = "75c9bc1b-ef1b-4463-9d7f-0ccb4b41e2b1"
DONOR_NAME = "VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS004_PUSH_DONOR"
DERIVATIVE_NAME = "VIDEO_CLONER_DZatr0EJt4B_MVP_V1__OSS004_VISIBLE_V1"
PUSH_BOUNDARY = 461
PUSH_DURATION = 8
SHAKE_SHOT = 3
SHAKE_WINDOW = (211, 216)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _find_optional(project: Any, name: str) -> Any:
    rows = [canary._optional(project, "GetTimelineByIndex", index) for index in range(1, int(canary._optional(project, "GetTimelineCount", default=0) or 0) + 1)]
    matches = [row for row in rows if row is not None and canary._name(row) == name]
    if len(matches) > 1:
        raise ValueError(f"timeline_name_ambiguous:{name}:{len(matches)}")
    return matches[0] if matches else None


def _media_rows(timeline: Any) -> list[Any]:
    rows = [item for item in (canary._optional(timeline, "GetItemListInTrack", "video", 1, default=[]) or []) if canary._optional(item, "GetMediaPoolItem") is not None]
    return sorted(rows, key=canary._item_start)


def _counts(timeline: Any) -> dict[str, int]:
    counts = {
        "V1": len([item for item in (canary._optional(timeline, "GetItemListInTrack", "video", 1, default=[]) or []) if canary._optional(item, "GetMediaPoolItem") is not None]),
        "V2": len(canary._optional(timeline, "GetItemListInTrack", "video", 2, default=[]) or []),
        "V3": len(canary._optional(timeline, "GetItemListInTrack", "video", 3, default=[]) or []),
        "A1": len(canary._optional(timeline, "GetItemListInTrack", "audio", 1, default=[]) or []),
    }
    if counts != {"V1": 8, "V2": 112, "V3": 69, "A1": 1}:
        raise ValueError(f"timeline_counts:{counts}")
    return counts


def _push_element(path: Path) -> str:
    _, contents = base._archive(path)
    matches = []
    for xml in base._text_files(contents).values():
        for match in base.TRANSITION_RE.finditer(xml):
            node = next(iter(ET.fromstring(match.group(0))))
            if (node.findtext("PrettyType") or node.findtext("Name") or "") == "Push":
                matches.append(match.group(0))
    if len(matches) != 1:
        raise ValueError(f"push_donor_count:{len(matches)}")
    return matches[0]


def _place_push(source: Path, target: Path, *, timeline_name: str, timeline_uuid: str, donor_element: str, at_frame: int) -> dict[str, Any]:
    selected = base.select_top_level(source, timeline_name)
    if selected["id"] != timeline_uuid:
        raise ValueError("timeline_uuid")
    infos, contents = base._archive(source)
    entry = selected["entry"]
    original = contents[entry].decode("utf-8-sig")
    vector_match, vector = base._inner(original, "VideoTrackVec")
    tracks = base.TRACK_RE.findall(vector)
    items_match, items = base._inner(tracks[0], "Items")
    clips = base.CLIP_RE.findall(items)
    left = next((i for i in range(len(clips) - 1) if base._number(clips[i], "Start") + base._number(clips[i], "Duration") == base._number(clips[i + 1], "Start") == at_frame), -1)
    if left < 0:
        raise ValueError(f"push_boundary:{at_frame}")
    start = at_frame - PUSH_DURATION // 2
    transition = re.sub(r'DbId="[0-9a-fA-F-]+"', lambda _: f'DbId="{uuid.uuid4()}"', donor_element)
    transition = re.sub(r"<Start>\d+</Start>", f"<Start>{start}</Start>", transition)
    transition = re.sub(r"<Duration>\d+</Duration>", f"<Duration>{PUSH_DURATION}</Duration>", transition)
    new_items = items.replace(clips[left], clips[left] + transition, 1)
    new_track = tracks[0][:items_match.start()] + f"<Items>{new_items}</Items>" + tracks[0][items_match.end():]
    new_vector = vector.replace(tracks[0], new_track, 1)
    contents[entry] = (original[:vector_match.start()] + f"<VideoTrackVec>{new_vector}</VideoTrackVec>" + original[vector_match.end():]).encode("utf-8")
    with zipfile.ZipFile(target, "w") as output:
        for info in infos:
            output.writestr(info, contents[info.filename])
    return {"family": "Push", "boundary": PUSH_BOUNDARY, "start": start, "duration": PUSH_DURATION, "end": start + PUSH_DURATION}


def _live_transitions(timeline: Any) -> list[dict[str, Any]]:
    base_frame = int(canary._optional(timeline, "GetStartFrame", default=0) or 0)
    rows = []
    for item in canary._optional(timeline, "GetItemListInTrack", "video", 1, default=[]) or []:
        if canary._optional(item, "GetMediaPoolItem") is None:
            rows.append({"name": canary._name(item), "start": canary._item_start(item) - base_frame, "duration": canary._item_duration(item)})
    rows.sort(key=lambda row: row["start"])
    if len(rows) != 4 or [row["name"] for row in rows].count("Blur Dissolve") != 3 or [row["name"] for row in rows].count("Push") != 1:
        raise RuntimeError(f"transition_readback:{rows!r}")
    return rows


def _apply_shake(item: Any, name: str) -> dict[str, Any]:
    before = [str(value) for value in (canary._optional(item, "GetFusionCompNameList", default=[]) or [])]
    if any(value.startswith("VC_OSS004_") for value in before):
        raise ValueError(f"shake_comp_collision:{before!r}")
    comp = canary._optional(item, "AddFusionComp", default=None)
    after = [str(value) for value in (canary._optional(item, "GetFusionCompNameList", default=[]) or [])]
    created = [value for value in after if value not in before]
    if comp is None or len(created) != 1 or canary._optional(item, "RenameFusionCompByName", created[0], name, default=False) is not True:
        raise RuntimeError("shake_comp_create")
    comp = canary._optional(item, "LoadFusionCompByName", name, default=None)
    media_in, media_out = fusion.find_tool(comp, "MediaIn"), fusion.find_tool(comp, "MediaOut")
    transform = canary._optional(comp, "AddTool", "Transform", -32768, -32768, default=None)
    if media_in is None or media_out is None or transform is None or not fusion.set_tool_name(transform, f"{name}_TRANSFORM"):
        raise RuntimeError("shake_transform_create")
    if not fusion.connect_tool(media_in, transform).get("ok") or not fusion.connect_tool(transform, media_out).get("ok"):
        raise RuntimeError("shake_graph")
    positions = ((0, [0.5, 0.5]), (1, [0.475, 0.515]), (2, [0.525, 0.485]), (3, [0.482, 0.49]), (4, [0.518, 0.512]), (5, [0.5, 0.5]))
    for input_name, keys in (("Center", positions), ("Size", ((0, 1.08), (5, 1.08)))):
        if not canary.animation.ensure_modifier(comp, transform, input_name).get("ok"):
            raise RuntimeError(f"shake_modifier:{input_name}")
        for frame, value in keys:
            if not canary.animation.write_key(transform, input_name, frame, value).get("ok"):
                raise RuntimeError(f"shake_key:{input_name}:{frame}")
    return {"comp": name, "shot": SHAKE_SHOT, "window": list(SHAKE_WINDOW), "graph": ["MediaIn", "Transform", "MediaOut"], "position_keys": len(positions), "scale": 1.08}


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "mode": MODE, "run_id": run_id, "failures": []}
    project = pool = baseline = donor = temporary = final = None
    temporary_uid = ""
    try:
        command, payload = context.get("command") or {}, (context.get("command") or {}).get("payload") or {}
        required = {"expected_project": rep.EXPECTED_PROJECT, "baseline_timeline": BASELINE_NAME, "baseline_uid": BASELINE_UID, "donor_timeline": DONOR_NAME, "derivative_timeline": DERIVATIVE_NAME}
        if command.get("task") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id or any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("command_authority")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        if _sha256(Path(__file__).resolve()) != payload.get("module_sha256"):
            raise ValueError("module_identity")
        manager = canary.carrier._call(resolve, "GetProjectManager")
        project = canary.carrier._call(manager, "GetCurrentProject")
        if project is None or canary._name(project) != rep.EXPECTED_PROJECT:
            raise ValueError("project_identity")
        donor = canary._find_timeline(project, DONOR_NAME)
        if canary._timeline_identity(donor)["unique_id"] != BASELINE_UID:
            raise ValueError("donor_provenance")
        baseline = _find_optional(project, BASELINE_NAME) or _find_optional(project, BASELINE_NAME + " copy")
        if baseline is None:
            raise ValueError("baseline_content")
        if canary._name(baseline) != BASELINE_NAME and canary._optional(baseline, "SetName", BASELINE_NAME, default=False) is not True:
            raise RuntimeError("baseline_name_restore")
        if _find_optional(project, DERIVATIVE_NAME) is not None:
            raise ValueError("baseline_or_derivative_identity")
        base_counts = _counts(baseline)
        base_transitions = [canary._name(item) for item in (canary._optional(baseline, "GetItemListInTrack", "video", 1, default=[]) or []) if canary._optional(item, "GetMediaPoolItem") is None]
        if base_transitions != ["Blur Dissolve"] * 3:
            raise ValueError(f"baseline_transitions:{base_transitions!r}")
        pool = canary.carrier._call(project, "GetMediaPool")
        report_dir = root / str(command["report_path"]).replace("/report.json", "")
        report_dir.mkdir(parents=True, exist_ok=True)
        donor_drt = report_dir / "push_donor.drt"
        export_type = getattr(resolve, "EXPORT_DRT", None)
        if export_type is None or canary._optional(donor, "Export", str(donor_drt), export_type, default=False) is not True:
            raise RuntimeError("push_donor_export")
        donor_element = _push_element(donor_drt)
        temporary = canary._optional(baseline, "DuplicateTimeline", DERIVATIVE_NAME, default=None)
        if temporary is None:
            raise RuntimeError("derivative_duplicate")
        temporary_uid = canary._timeline_identity(temporary)["unique_id"]
        unpatched = report_dir / "visible_unpatched.drt"
        if canary._optional(temporary, "Export", str(unpatched), export_type, default=False) is not True:
            raise RuntimeError("derivative_export")
        target = base.select_top_level(unpatched, DERIVATIVE_NAME)
        patched = report_dir / "visible_push.drt"
        base_frame = int(canary._optional(baseline, "GetStartFrame", default=0) or 0)
        push = _place_push(unpatched, patched, timeline_name=DERIVATIVE_NAME, timeline_uuid=target["id"], donor_element=donor_element, at_frame=base_frame + PUSH_BOUNDARY)
        if canary._optional(project, "SetCurrentTimeline", baseline, default=False) is not True or canary._optional(pool, "DeleteTimelines", [temporary], default=False) is not True:
            raise RuntimeError("temporary_cleanup")
        temporary = None
        final = canary._optional(pool, "ImportTimelineFromFile", str(patched), default=None) or _find_optional(project, DERIVATIVE_NAME)
        if final is None or canary._optional(project, "SetCurrentTimeline", final, default=False) is not True:
            raise RuntimeError("derivative_import")
        transitions = _live_transitions(final)
        items = _media_rows(final)
        if len(items) != 8:
            raise RuntimeError(f"media_count:{len(items)}")
        shake = _apply_shake(items[SHAKE_SHOT - 1], f"VC_OSS004_CAMERA_SHAKE_{run_id.rsplit('_', 1)[-1][:12]}")
        counts = _counts(final)
        if counts != base_counts or _counts(baseline) != base_counts:
            raise RuntimeError("preservation")
        donor_uid = canary._timeline_identity(donor)["unique_id"]
        if canary._optional(pool, "DeleteTimelines", [donor], default=False) is not True or _find_optional(project, DONOR_NAME) is not None:
            raise RuntimeError(f"donor_cleanup:{donor_uid}")
        saved = canary._optional(manager, "SaveProject", default=False)
        if saved is not True:
            raise RuntimeError("save_project")
        result.update({"ok": True, "verification": "PASS", "classification": {"211": "CAMERA_SHAKE_VFX", "461": "REAL_TRANSITION", "629": "IGNORE_OTHER_END_CARD_REVEAL"}, "push": push, "shake": shake, "transitions": transitions, "counts": counts, "derivative": canary._timeline_identity(final), "current_timeline": canary._timeline_identity(canary._optional(project, "GetCurrentTimeline", default=None)), "save_project_return": saved})
    except Exception as exc:
        result["failures"].append(f"{type(exc).__name__}: {exc}")
        if project is not None and pool is not None and temporary is not None and temporary_uid and canary._timeline_identity(temporary)["unique_id"] == temporary_uid:
            if baseline is not None:
                canary._optional(project, "SetCurrentTimeline", baseline, default=False)
            result["temporary_cleanup"] = canary._optional(pool, "DeleteTimelines", [temporary], default=False) is True
    return result


if os.environ.get("VC_DISABLE_WORKSPACE_AUTORUN") != "1" and "resolve" in globals() and "context" in globals():
    result = run(resolve, context)
