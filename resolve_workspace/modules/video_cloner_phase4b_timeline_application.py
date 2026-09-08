"""Import and verify one cut-only Phase 4A FCPXML timeline through the repository bridge."""
from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

TASK_ID = "VIDEO_CLONER_PHASE4B_RESOLVE_TIMELINE_APPLICATION_V1"
MODE = "phase4b_import_cut_only_fcpxml"


def safe(obj: Any, method: str, *args: Any, default: Any = None) -> Any:
    try:
        return getattr(obj, method)(*args)
    except Exception:
        return default


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def as_int(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def fcpxml_frames(value: str, fps: int) -> int:
    token = str(value or "").strip()
    if token.endswith("s"):
        token = token[:-1]
    if not token:
        raise ValueError("fcpxml_time")
    return int(Fraction(token) * fps)


def file_url_path(value: str) -> Path:
    parsed = urlparse(value)
    if parsed.scheme != "file":
        raise ValueError("fcpxml_asset_scheme")
    decoded = unquote(parsed.path)
    if os.name == "nt" and decoded.startswith("/") and len(decoded) > 2 and decoded[2] == ":":
        decoded = decoded[1:]
    return Path(decoded).resolve()


def parse_fcpxml_contract(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("fcpxml_missing_or_empty")
    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        raise ValueError(f"fcpxml_parse:{exc}") from exc
    if root.tag != "fcpxml" or root.get("version") != "1.10":
        raise ValueError("fcpxml_root_version")
    project = root.find("./library/event/project")
    sequence = root.find("./library/event/project/sequence")
    spine = root.find("./library/event/project/sequence/spine")
    format_element = root.find("./resources/format")
    assets = [row for row in root.findall("./resources/asset") if row.get("hasVideo") == "1"]
    if project is None or sequence is None or spine is None or format_element is None or len(assets) != 1:
        raise ValueError("fcpxml_structure")
    timeline_name = str(project.get("name") or "")
    asset_id = str(assets[0].get("id") or "")
    if not timeline_name or not asset_id:
        raise ValueError("fcpxml_identity")
    frame_duration = str(format_element.get("frameDuration") or "")
    if frame_duration != "1/24s":
        raise ValueError(f"fcpxml_timebase:{frame_duration}")
    forbidden = {tag: len(root.findall(f".//{tag}")) for tag in ("transition", "title", "timeMap", "timept", "adjust-transform", "filter-video")}
    if any(forbidden.values()):
        raise ValueError(f"fcpxml_forbidden:{forbidden}")
    clips = []
    for index, element in enumerate(list(spine), start=1):
        if element.tag != "asset-clip" or element.get("lane") is not None or element.get("ref") != asset_id:
            raise ValueError(f"fcpxml_spine_item:{index}:{element.tag}")
        clips.append({
            "index": index,
            "name": str(element.get("name") or ""),
            "timeline_start": fcpxml_frames(element.get("offset") or "", 24),
            "source_start": fcpxml_frames(element.get("start") or "", 24),
            "duration": fcpxml_frames(element.get("duration") or "", 24),
        })
    if not clips:
        raise ValueError("fcpxml_clip_count:0")
    expected_start = 0
    for clip in clips:
        if clip["timeline_start"] != expected_start or clip["source_start"] != expected_start or clip["duration"] <= 0:
            raise ValueError(f"fcpxml_mapping:{clip['index']}")
        expected_start += clip["duration"]
    duration_frames = fcpxml_frames(sequence.get("duration") or "", 24)
    if duration_frames <= 0 or expected_start != duration_frames:
        raise ValueError("fcpxml_duration")
    source_path = file_url_path(str(assets[0].get("src") or ""))
    if not source_path.is_file() or source_path.stat().st_size == 0:
        raise ValueError("fcpxml_source_media")
    return {
        "version": "1.10",
        "fps": 24,
        "timeline_name": timeline_name,
        "duration_frames": duration_frames,
        "clips": clips,
        "source_path": str(source_path),
        "forbidden_xml_counts": forbidden,
    }


def timeline_name(timeline: Any) -> str:
    return str(safe(timeline, "GetName", default="") or "")


def project_timelines(project: Any) -> list[Any]:
    count = int(safe(project, "GetTimelineCount", default=0) or 0)
    return [row for index in range(1, count + 1) if (row := safe(project, "GetTimelineByIndex", index)) is not None]


def find_timelines(project: Any, name: str) -> list[Any]:
    return [timeline for timeline in project_timelines(project) if timeline_name(timeline) == name]


def media_path(item: Any) -> str:
    media = safe(item, "GetMediaPoolItem")
    properties = safe(media, "GetClipProperty", default={}) if media is not None else {}
    if isinstance(properties, dict):
        for key in ("File Path", "FilePath", "Path"):
            if properties.get(key):
                return str(Path(str(properties[key])).resolve())
    return ""


def item_snapshot(item: Any, track_index: int) -> dict[str, Any]:
    properties = safe(item, "GetProperty", default={})
    if not isinstance(properties, dict):
        properties = {}
    selected = {key: properties.get(key) for key in ("ZoomX", "ZoomY", "PositionX", "PositionY", "RotationAngle", "RetimeSpeed") if key in properties}
    return {
        "track_index": track_index,
        "name": str(safe(item, "GetName", default="") or ""),
        "start": as_int(safe(item, "GetStart")),
        "end": as_int(safe(item, "GetEnd")),
        "duration": as_int(safe(item, "GetDuration")),
        "left_offset": as_int(safe(item, "GetLeftOffset")),
        "media_path": media_path(item),
        "has_media_pool_item": safe(item, "GetMediaPoolItem") is not None,
        "fusion_comp_count": int(safe(item, "GetFusionCompCount", default=0) or 0),
        "properties": selected,
    }


def timeline_snapshot(timeline: Any) -> dict[str, Any]:
    video_tracks = int(safe(timeline, "GetTrackCount", "video", default=0) or 0)
    audio_tracks = int(safe(timeline, "GetTrackCount", "audio", default=0) or 0)
    video_rows = []
    audio_rows = []
    for track in range(1, video_tracks + 1):
        video_rows.extend(item_snapshot(item, track) for item in list(safe(timeline, "GetItemListInTrack", "video", track, default=[]) or []))
    for track in range(1, audio_tracks + 1):
        audio_rows.extend(item_snapshot(item, track) for item in list(safe(timeline, "GetItemListInTrack", "audio", track, default=[]) or []))
    settings = {
        "timelineFrameRate": safe(timeline, "GetSetting", "timelineFrameRate"),
        "timelinePlaybackFrameRate": safe(timeline, "GetSetting", "timelinePlaybackFrameRate"),
    }
    snapshot = {
        "name": timeline_name(timeline),
        "start_frame": as_int(safe(timeline, "GetStartFrame", default=0)) or 0,
        "end_frame": as_int(safe(timeline, "GetEndFrame")),
        "settings": settings,
        "video_track_count": video_tracks,
        "audio_track_count": audio_tracks,
        "video_items": video_rows,
        "audio_items": audio_rows,
    }
    snapshot["signature"] = canonical_sha256({key: value for key, value in snapshot.items() if key != "signature"})
    return snapshot


def timeline_inventory(project: Any) -> list[dict[str, Any]]:
    return [{"name": timeline_name(timeline), "signature": timeline_snapshot(timeline)["signature"]} for timeline in project_timelines(project)]


def same_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def validate_target(timeline: Any, contract: dict[str, Any], target_name: str) -> dict[str, Any]:
    snapshot = timeline_snapshot(timeline)
    if snapshot["name"] != target_name:
        raise ValueError("target_timeline_name")
    fps_values = [value for value in snapshot["settings"].values() if value not in (None, "")]
    if not fps_values or any(abs(float(value) - 24.0) > 1e-6 for value in fps_values):
        raise ValueError(f"target_timebase:{fps_values}")
    rows = snapshot["video_items"]
    if len(rows) != len(contract["clips"]) or snapshot["audio_items"]:
        raise ValueError(f"target_track_counts:video={len(rows)}:audio={len(snapshot['audio_items'])}")
    nonempty_tracks = sorted({row["track_index"] for row in rows})
    if len(nonempty_tracks) != 1:
        raise ValueError(f"target_primary_track:{nonempty_tracks}")
    base = snapshot["start_frame"]
    nondefault_transform = 0
    retime = 0
    fusion = 0
    for expected, actual in zip(contract["clips"], sorted(rows, key=lambda row: (row["start"], row["track_index"]))):
        if actual["start"] is None or actual["duration"] is None or actual["left_offset"] is None:
            raise ValueError(f"target_item_readback:{expected['index']}")
        if actual["start"] - base != expected["timeline_start"] or actual["duration"] != expected["duration"] or actual["left_offset"] != expected["source_start"]:
            raise ValueError(f"target_item_mapping:{expected['index']}")
        if actual["end"] is None or actual["end"] - actual["start"] not in {expected["duration"], expected["duration"] - 1}:
            raise ValueError(f"target_item_end:{expected['index']}")
        if not actual["has_media_pool_item"] or not same_path(actual["media_path"], contract["source_path"]):
            raise ValueError(f"target_item_media:{expected['index']}")
        properties = actual["properties"]
        for key, default in (("ZoomX", 1.0), ("ZoomY", 1.0), ("PositionX", 0.0), ("PositionY", 0.0), ("RotationAngle", 0.0)):
            if key in properties and abs(float(properties[key]) - default) > 1e-6:
                nondefault_transform += 1
        if "RetimeSpeed" in properties and abs(float(properties["RetimeSpeed"]) - 100.0) > 1e-6:
            retime += 1
        fusion += actual["fusion_comp_count"]
    relative_end = max(row["start"] - base + row["duration"] for row in rows)
    if relative_end != contract["duration_frames"]:
        raise ValueError(f"target_duration:{relative_end}")
    forbidden = {
        "speed_retime": retime,
        "animated_zoom_transform": nondefault_transform,
        "whip_transitions": 0,
        "slide_transitions": 0,
        "blur_filters": 0,
        "transition_items": 0,
        "caption_title_items": 0,
        "flash_carriers": fusion,
        "occlusion_components": 0,
        "fusion_compositions": fusion,
    }
    if any(forbidden.values()):
        raise ValueError(f"target_forbidden:{forbidden}")
    return {"ok": True, "clip_count": len(contract["clips"]), "fps": contract["fps"], "duration_frames": contract["duration_frames"], "primary_video_track": nonempty_tracks[0], "forbidden_operation_counts": forbidden, "snapshot": snapshot}


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    report: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "run_id": run_id, "mode": MODE, "classification": None, "import_call_count": 0, "save_project_count": 0, "failures": []}
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        if command.get("task") != TASK_ID or command.get("run_id") != run_id or command.get("mode") != MODE:
            raise ValueError("command_identity")
        if payload.get("import_permitted") is not True or payload.get("replace_existing_timeline") is not False or payload.get("save_project") is not False:
            raise ValueError("mutation_authority")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        output_dir = root / str(payload.get("report_dir") or "")
        fcpxml = Path(str(payload.get("fcpxml_path") or "")).resolve()
        if sha256(fcpxml) != payload.get("fcpxml_sha256"):
            raise ValueError("fcpxml_identity")
        contract = parse_fcpxml_contract(fcpxml)
        expected_contract = {
            "expected_clip_count": len(contract["clips"]),
            "expected_duration_frames": contract["duration_frames"],
            "expected_fps": contract["fps"],
        }
        if any(type(payload.get(key)) is not int or payload.get(key) != value for key, value in expected_contract.items()):
            raise ValueError("fcpxml_payload_expectations")
        expected_project = str(payload.get("expected_project") or "")
        target_name = str(payload.get("target_timeline_name") or "")
        protected_name = str(payload.get("protected_timeline_name") or "")
        if target_name != contract["timeline_name"] or (protected_name and protected_name == target_name):
            raise ValueError("timeline_authority")
        manager = safe(resolve, "GetProjectManager")
        project = safe(manager, "GetCurrentProject")
        project_name = str(safe(project, "GetName", default="") or "") if project is not None else ""
        if project is None or project_name != expected_project:
            raise ValueError(f"project_identity:{project_name}")
        media_pool = safe(project, "GetMediaPool")
        if media_pool is None:
            raise ValueError("media_pool_missing")
        inventory_before = timeline_inventory(project)
        write_json(output_dir / "pre_timeline_inventory.json", {"project_name": project_name, "timelines": inventory_before})
        existing = find_timelines(project, target_name)
        if len(existing) > 1:
            raise ValueError("target_timeline_duplicate_collision")
        if protected_name and sum(row["name"] == protected_name for row in inventory_before) != 1:
            raise ValueError("protected_timeline_identity")
        non_target_before = [row for row in inventory_before if row["name"] != target_name]
        if existing:
            target = existing[0]
            classification = "ALREADY_VALID_REUSED"
        else:
            returned = safe(media_pool, "ImportTimelineFromFile", str(fcpxml), default=None)
            report["import_call_count"] = 1
            matches = find_timelines(project, target_name)
            if len(matches) != 1:
                raise ValueError(f"import_target_identity:{len(matches)}")
            target = matches[0]
            if returned not in (None, False, True) and timeline_name(returned) != target_name:
                raise ValueError("import_returned_timeline_identity")
            classification = "NEW_ISOLATED_TIMELINE_IMPORTED"
        target_validation = validate_target(target, contract, target_name)
        write_json(output_dir / "target_timeline_snapshot.json", target_validation)
        if not bool(safe(project, "SetCurrentTimeline", target, default=False)) and safe(project, "GetCurrentTimeline") is not target:
            raise ValueError("target_selection")
        inventory_after = timeline_inventory(project)
        expected_delta = 1 if classification == "NEW_ISOLATED_TIMELINE_IMPORTED" else 0
        non_target_after = [row for row in inventory_after if row["name"] != target_name]
        inventory_key = lambda row: (row["name"], row["signature"])
        if len(inventory_after) - len(inventory_before) != expected_delta or sum(row["name"] == target_name for row in inventory_after) != 1:
            raise ValueError("timeline_inventory_delta")
        if Counter(map(inventory_key, non_target_after)) != Counter(map(inventory_key, non_target_before)):
            raise ValueError("non_target_timeline_changed")
        protection = {"ok": True, "protected_timeline_name": protected_name or None, "unchanged": True, "before": non_target_before, "after": non_target_after, "inventory_before": inventory_before, "inventory_after": inventory_after, "inventory_delta": expected_delta}
        write_json(output_dir / "protected_timeline_evidence.json", protection)
        result = {"ok": True, "classification": classification, "project_name": project_name, "target_timeline_name": target_name, "protected_timeline_name": protected_name or None, "fcpxml_path": str(fcpxml), "fcpxml_sha256": sha256(fcpxml), "operation_id": payload.get("operation_id"), "import_call_count": report["import_call_count"], "save_project_count": 0, "target": target_validation, "protected_timeline_unchanged": True, "timeline_inventory_before": inventory_before, "timeline_inventory_after": inventory_after}
        write_json(output_dir / "timeline_import_result.json", result)
        report.update(result)
    except Exception as exc:
        report["failures"] = [f"{type(exc).__name__}: {exc}"]
    return report
