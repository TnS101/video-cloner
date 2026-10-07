"""Read-only live identity probe for the Reel #2 ``social,`` caption."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping
from xml.etree import ElementTree


TASK_ID = "VIDEO_CLONER_STEP4_REEL2_SOCIAL_TARGET_READONLY_PREFLIGHT_V1"
MODE = "step4_reel2_social_target_readonly_preflight"
PROJECT_NAME = "New Project 1"
TIMELINE_NAME = "DcJRJtUKScu_offline_timeline_v1"
TIMELINE_UID = "4ad2a3c3-031c-464d-96aa-76a045608ad6"
ITEM_NAME = "VC Caption 0045 - social,"
TRACK = 2
START = 365
END = 376
TEXT = "social,"
CANONICAL_WINDOW = [359, 383]
LOCAL_ANIMATION_RANGE = [0, 23]
ZERO_MUTATIONS = {
    "saves": 0, "creates": 0, "deletes": 0, "title_writes": 0,
    "modifier_writes": 0, "keyframe_writes": 0, "imports": 0,
    "relinks": 0, "replaces": 0, "timeline_selections": 0,
}


def _load_base() -> Any:
    path = Path(__file__).with_name("video_cloner_phase6_textplus_application.py")
    spec = importlib.util.spec_from_file_location("vc_social_target_phase6", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load_base()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_command(command: Mapping[str, Any], run_id: str) -> Mapping[str, Any]:
    payload = command.get("payload") or {}
    required_false = (
        "mutation_permitted", "save_project", "create_permitted",
        "delete_permitted", "title_write_permitted", "modifier_write_permitted",
        "keyframe_write_permitted", "import_permitted", "relink_permitted",
        "replace_permitted", "timeline_selection_permitted",
    )
    if (
        command.get("task_id") != TASK_ID
        or command.get("mode") != MODE
        or command.get("run_id") != run_id
        or payload.get("read_only") is not True
        or any(payload.get(key) is not False for key in required_false)
    ):
        raise ValueError("read_only_command_authority")
    expected = {
        "expected_project": PROJECT_NAME,
        "target_timeline_name": TIMELINE_NAME,
        "expected_timeline_uid": TIMELINE_UID,
        "expected_item_name": ITEM_NAME,
        "expected_track": TRACK,
        "expected_start": START,
        "expected_end": END,
        "expected_text": TEXT,
        "canonical_window": CANONICAL_WINDOW,
        "local_animation_range": LOCAL_ANIMATION_RANGE,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("target_authority")
    return payload


def _repository_file(root: Path, value: Any) -> Path:
    path = Path(str(value or ""))
    path = path.resolve() if path.is_absolute() else (root / path).resolve()
    path.relative_to(root)
    if not path.is_file():
        raise ValueError(f"authority_missing:{path}")
    return path


def verify_authority(root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    report_path = _repository_file(root, payload.get("accepted_report_path"))
    export_path = _repository_file(root, payload.get("exported_fcpxml_path"))
    if _sha256(report_path) != payload.get("accepted_report_sha256"):
        raise ValueError("accepted_report_hash")
    if _sha256(export_path) != payload.get("exported_fcpxml_sha256"):
        raise ValueError("exported_fcpxml_hash")
    accepted = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if any((
        accepted.get("ok") is not True,
        accepted.get("classification") != "VIDEO_CLONER_V1_LIVE_ACCEPTED",
        accepted.get("project_name") != PROJECT_NAME,
        accepted.get("target_timeline_name") != TIMELINE_NAME,
        accepted.get("target_unique_id") != TIMELINE_UID,
        accepted.get("ownership_classification") != "NEWLY_CREATED",
        (accepted.get("applied_operation_counts") or {}).get("textplus_titles") != 92,
    )):
        raise ValueError("accepted_report_contract")
    titles = []
    for title in ElementTree.parse(export_path).getroot().iter("title"):
        name = str(title.get("name") or "")
        text = "".join(title.itertext()).strip()
        if name == ITEM_NAME:
            titles.append({
                "name": name,
                "lane": int(title.get("lane") or 0),
                "start": _frames(title.get("offset")),
                "duration": _frames(title.get("duration")),
                "text": text,
            })
    if titles != [{"name": ITEM_NAME, "lane": 1, "start": START, "duration": END - START, "text": TEXT}]:
        raise ValueError("exported_title_contract")
    return {
        "accepted_report": str(report_path),
        "exported_fcpxml": str(export_path),
        "timeline_ownership": "NEWLY_CREATED",
        "historical_caption_count": 92,
        "title": titles[0],
    }


def _frames(value: Any) -> int:
    raw = str(value or "").removesuffix("s")
    numerator, denominator = raw.split("/", 1)
    return round(float(numerator) / float(denominator) * 24)


def _timeline_identity(timeline: Any) -> dict[str, str]:
    return {
        "name": str(BASE._safe(timeline, "GetName", default="") or ""),
        "unique_id": str(BASE._safe(timeline, "GetUniqueId", default="") or ""),
    }


def _modifier_state(tool: Any, input_name: str) -> dict[str, Any]:
    input_object = BASE._safe(tool, "FindInput", input_name, default=None)
    output = BASE._safe(input_object, "GetConnectedOutput", default=None) if input_object is not None else None
    modifier = BASE._safe(output, "GetTool", default=None) if output is not None else None
    attrs = BASE._safe(modifier, "GetAttrs", default={}) if modifier is not None else {}
    keyframes = BASE._safe(modifier, "GetKeyFrames", default={}) if modifier is not None else {}
    return {
        "connected": output is not None,
        "modifier_type": str((attrs or {}).get("TOOLS_RegID") or "") or None,
        "keyframes": json.loads(json.dumps(keyframes or {}, default=str)),
    }


def _fusion_state(item: Any) -> dict[str, Any]:
    count = int(BASE._safe(item, "GetFusionCompCount", default=0) or 0)
    nodes = []
    textplus = []
    for index in range(1, count + 1):
        comp = BASE._safe(item, "GetFusionCompByIndex", index, default=None)
        tools = BASE._safe(comp, "GetToolList", False, default={}) if comp is not None else {}
        for tool in (tools.values() if isinstance(tools, Mapping) else []):
            attrs = BASE._safe(tool, "GetAttrs", default={}) or {}
            row = {
                "name": str(attrs.get("TOOLS_Name") or ""),
                "reg_id": str(attrs.get("TOOLS_RegID") or attrs.get("TOOLST_RegID") or ""),
            }
            nodes.append(row)
            if row["reg_id"] == "TextPlus":
                textplus.append({**row, "styled_text": str(BASE._safe(tool, "GetInput", "StyledText", 0, default="") or ""),
                                 "modifiers": {name: _modifier_state(tool, name) for name in ("Center", "Size")}})
    return {"fusion_composition_count": count, "fusion_nodes": nodes, "textplus_nodes": textplus,
            "textplus_node_count": len(textplus)}


def inspect(resolve: Any) -> dict[str, Any]:
    manager = BASE._safe(resolve, "GetProjectManager", default=None)
    project = BASE._safe(manager, "GetCurrentProject", default=None)
    project_name = str(BASE._safe(project, "GetName", default="") or "")
    if project is None or project_name != PROJECT_NAME:
        raise ValueError(f"project_identity:{project_name}")
    timelines = BASE._timelines(project)
    name_matches = [timeline for timeline in timelines if _timeline_identity(timeline)["name"] == TIMELINE_NAME]
    if len(name_matches) != 1:
        raise ValueError(f"timeline_name_occurrence:{len(name_matches)}")
    timeline = name_matches[0]
    identity = _timeline_identity(timeline)
    if identity["unique_id"] != TIMELINE_UID:
        raise ValueError(f"timeline_uid:{identity['unique_id']}")

    structural = []
    for track in range(1, int(BASE._safe(timeline, "GetTrackCount", "video", default=0) or 0) + 1):
        for item in list(BASE._safe(timeline, "GetItemListInTrack", "video", track, default=[]) or []):
            start = int(BASE._safe(item, "GetStart", default=-1))
            end = int(BASE._safe(item, "GetEnd", default=-1))
            if track == TRACK and start == START and end == END:
                structural.append((track, item))
    if len(structural) != 1:
        raise ValueError(f"structural_target_occurrence:{len(structural)}")
    track, item = structural[0]
    uid = str(BASE._safe(item, "GetUniqueId", default="") or "")
    if not uid:
        raise ValueError("timeline_item_uid")
    item_name = str(BASE._safe(item, "GetName", default="") or "")
    if item_name not in {"Text", "Basic Title", ITEM_NAME}:
        raise ValueError(f"item_identity:{item_name}")
    styled_text = BASE._title_text(item)
    if styled_text != TEXT:
        raise ValueError(f"styled_text:{styled_text}")
    duration = int(BASE._safe(item, "GetDuration", default=end - start))
    if duration != END - START:
        raise ValueError(f"duration:{duration}")
    properties = BASE._safe(item, "GetProperty", default={}) or {}
    fusion = _fusion_state(item)
    target = {
        "timeline_item_uid": uid,
        "item_name": item_name,
        "item_type": str(properties.get("Type") or properties.get("Clip Type") or "") or None,
        "track": track, "start": start, "end": end, "duration": duration,
        "styled_text": styled_text, **fusion,
    }
    if fusion["fusion_composition_count"] == 0 and fusion["textplus_node_count"] == 0:
        classification = "TEXTPLUS_RECONSTRUCTION_REQUIRED"
    elif fusion["fusion_composition_count"] >= 1 and fusion["textplus_node_count"] == 1:
        classification = "TEXTPLUS_TARGET_EXISTS"
    else:
        raise ValueError("fusion_textplus_structure")
    return {
        "project": project_name,
        "timeline": identity,
        "classification": classification,
        "target_unique": True,
        "target": target,
        "compatibility": {
            "persisted_window": [START, END],
            "canonical_visual_window": CANONICAL_WINDOW,
            "required_local_animation_range": LOCAL_ANIMATION_RANGE,
            "can_host_unchanged": duration > LOCAL_ANIMATION_RANGE[1] and start == CANONICAL_WINDOW[0] and end == CANONICAL_WINDOW[1],
        },
    }


def _queue_preflight(root: Path, run_id: str) -> dict[str, Any]:
    queue = root / ".agent" / "commands"
    pending = list((queue / "pending").glob("*.json"))
    running = list((queue / "running").glob("*.json"))
    if pending or len(running) != 1:
        raise ValueError(f"queue_state:{len(pending)}:{len(running)}")
    command = json.loads(running[0].read_text(encoding="utf-8-sig"))
    if command.get("run_id") != run_id or command.get("task_id") != TASK_ID:
        raise ValueError("queue_identity")
    return {"pending": 0, "running": 1, "command": running[0].name}


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    command = context.get("command") or {}
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    report = {
        "ok": False, "task_id": TASK_ID, "run_id": run_id, "mode": MODE,
        "classification": "READONLY_PREFLIGHT_BLOCKED", "read_only": True,
        "mutation_counts": dict(ZERO_MUTATIONS), "failures": [],
    }
    try:
        payload = validate_command(command, run_id)
        root = Path(str(payload.get("repository_root") or "")).resolve()
        if not (root / "AGENTS.md").is_file():
            raise ValueError("repository_identity")
        report["queue_preflight"] = _queue_preflight(root, run_id)
        report["authority"] = verify_authority(root, payload)
        before = [BASE.timeline_snapshot(timeline) for timeline in BASE._timelines(BASE._safe(BASE._safe(resolve, "GetProjectManager"), "GetCurrentProject"))]
        result = inspect(resolve)
        after = [BASE.timeline_snapshot(timeline) for timeline in BASE._timelines(BASE._safe(BASE._safe(resolve, "GetProjectManager"), "GetCurrentProject"))]
        if before != after:
            raise ValueError("resolve_state_changed")
        report.update(result)
        report["protected_state_unchanged"] = True
        report["reel1_unchanged"] = True
        report["reel2_unchanged"] = True
        report["ok"] = True
    except Exception as exc:
        report["failures"] = [f"{type(exc).__name__}: {exc}"]
    return report
