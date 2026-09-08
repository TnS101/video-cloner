"""Locate an accepted Flash carrier across every timeline without mutation."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Mapping

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("vc_flash_helpers_for_location_probe", _HERE / "advanced_transition_flash_application_v1.py")
if _SPEC is None or _SPEC.loader is None:
    raise ImportError("cannot_load_flash_helpers")
V1 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(V1)

TASK_ID = "VIDEO_CLONER_PHASE5_PHASE4C1_FLASH_LOCATION_PROBE_V1"
MODE = "phase4c1_flash_location_probe"
ACTION = "inspect_flash_location_project_wide"
CLASSIFICATIONS = {
    "FLASH_EXACT_MATCH_EXPECTED_TARGET",
    "FLASH_EXACT_MATCH_OTHER_TIMELINE",
    "FLASH_PARTIAL_MATCH_ONLY",
    "FLASH_ABSENT_PROJECT_WIDE",
    "FLASH_MULTIPLE_EXACT_MATCHES",
}
ZERO_MUTATIONS = {"selections": 0, "creates": 0, "deletes": 0, "renames": 0, "imports": 0, "media_imports": 0, "fusion_writes": 0, "saves": 0}


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def validate_identity(identity: Mapping[str, Any]) -> None:
    required = {"name", "start", "end", "duration", "media_pool_item_name", "fusion_tool_name", "alpha_keyframes"}
    if set(identity) != required:
        raise ValueError("identity_fields")
    if not str(identity["name"]) or not str(identity["media_pool_item_name"]) or not str(identity["fusion_tool_name"]):
        raise ValueError("identity_names")
    start, end, duration = (as_int(identity[key], -1) for key in ("start", "end", "duration"))
    if start < 0 or duration <= 0 or end != start + duration:
        raise ValueError("identity_range")
    keyframes = identity["alpha_keyframes"]
    if not isinstance(keyframes, list) or not keyframes or any(not isinstance(row, list) or len(row) != 2 for row in keyframes):
        raise ValueError("identity_alpha")


def media_identity(item: Any) -> tuple[str, str, bool]:
    media = V1.safe_call(item, "GetMediaPoolItem", default=None)
    if media is None:
        return "", "", False
    name = str(V1.safe_call(media, "GetName", default="") or "")
    properties = V1.safe_call(media, "GetClipProperty", default={}) or {}
    source = ""
    if isinstance(properties, Mapping):
        for key in ("File Path", "FilePath", "Path", "Clip Name"):
            if properties.get(key):
                source = str(properties[key])
                break
    if not source:
        for key in ("File Path", "FilePath"):
            value = V1.safe_call(media, "GetClipProperty", key, default="")
            if value:
                source = str(value)
                break
    return name, source, True


def read_value(tool: Any, name: str, frame: int | None = None) -> dict[str, Any]:
    row = V1.read_input(tool, name, frame)
    return {"ok": row.get("ok") is True, "value": row.get("value"), "method": row.get("method")}


def fusion_evidence(item: Any, identity: Mapping[str, Any]) -> dict[str, Any]:
    expected_name = str(identity["fusion_tool_name"])
    count = as_int(V1.safe_call(item, "GetFusionCompCount", default=0), 0)
    relevant_names: list[str] = []
    matched_tool = None
    for index in range(1, count + 1):
        comp = V1.safe_call(item, "GetFusionCompByIndex", index, default=None)
        for tool in V1.fusion_tools(comp):
            name = V1.fusion_tool_name(tool)
            if name == expected_name or name.startswith("VC_FLASH_BG_"):
                relevant_names.append(name)
            if name == expected_name and matched_tool is None:
                matched_tool = tool
    colors = {channel: read_value(matched_tool, input_name) if matched_tool is not None else {"ok": False, "value": None, "method": None} for channel, input_name in (("red", "TopLeftRed"), ("green", "TopLeftGreen"), ("blue", "TopLeftBlue"))}
    alpha = [
        {"frame": as_int(frame), "expected": float(expected), "readback": read_value(matched_tool, "TopLeftAlpha", as_int(frame)) if matched_tool is not None else {"ok": False, "value": None, "method": None}}
        for frame, expected in identity["alpha_keyframes"]
    ]
    policy = bool(
        matched_tool is not None
        and all(row["ok"] and V1.numeric_close(row["value"], 1.0) for row in colors.values())
        and all(row["readback"]["ok"] and V1.numeric_close(row["readback"]["value"], row["expected"]) for row in alpha)
    )
    return {"composition_count": count, "relevant_tool_names": sorted(set(relevant_names)), "tool_match": matched_tool is not None, "policy_match": policy, "colors": colors, "alpha_keyframes": alpha}


def inspect_item(timeline_name: str, timeline_index: int, track_index: int, item: Any, identity: Mapping[str, Any]) -> dict[str, Any]:
    name = V1.item_name(item)
    start, end, duration = V1.item_start(item), V1.item_end(item), V1.item_duration(item)
    media_name, source, has_media = media_identity(item)
    fusion = fusion_evidence(item, identity)
    signals = {
        "name_match": name == identity["name"],
        "range_match": start == identity["start"] and end == identity["end"],
        "duration_match": duration == identity["duration"],
        "neutral_media_match": has_media and media_name == identity["media_pool_item_name"],
        "fusion_tool_match": fusion["tool_match"],
        "fusion_policy_match": fusion["policy_match"],
    }
    exact = all(signals.values())
    meaningful = any(signals[key] for key in ("name_match", "range_match", "neutral_media_match", "fusion_tool_match", "fusion_policy_match"))
    return {
        "timeline_name": timeline_name,
        "timeline_index": timeline_index,
        "track_index": track_index,
        "item_name": name,
        "start": start,
        "end": end,
        "duration": duration,
        "media_pool_item_name": media_name,
        "media_source_identity": source,
        "has_media_pool_item": has_media,
        "fusion": fusion,
        **signals,
        "classification": "EXACT_FLASH_MATCH" if exact else ("PARTIAL_FLASH_MATCH" if meaningful else "NO_FLASH_MATCH"),
    }


def project_classification(matches: list[dict[str, Any]], expected_target: str) -> str:
    exact = [row for row in matches if row["classification"] == "EXACT_FLASH_MATCH"]
    if len(exact) > 1:
        return "FLASH_MULTIPLE_EXACT_MATCHES"
    if len(exact) == 1:
        return "FLASH_EXACT_MATCH_EXPECTED_TARGET" if exact[0]["timeline_name"] == expected_target else "FLASH_EXACT_MATCH_OTHER_TIMELINE"
    return "FLASH_PARTIAL_MATCH_ONLY" if matches else "FLASH_ABSENT_PROJECT_WIDE"


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    report: dict[str, Any] = {
        "ok": False,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "action": ACTION,
        "operation_id": None,
        "read_only": True,
        "timeline_modified": False,
        "mutation_counts": dict(ZERO_MUTATIONS),
        "project_name": None,
        "current_timeline_name": None,
        "expected_target_timeline_name": None,
        "expected_target_occurrence_count": 0,
        "timeline_count": 0,
        "timeline_inventory": [],
        "inspected_video_item_count": 0,
        "matches": [],
        "exact_match_count": 0,
        "partial_match_count": 0,
        "classification": None,
        "failures": [],
    }
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        if command.get("task") != TASK_ID or command.get("run_id") != run_id or command.get("mode") != MODE or payload.get("action") != ACTION:
            raise ValueError("command_identity")
        if payload.get("read_only") is not True or payload.get("mutation_permitted") is not False:
            raise ValueError("read_only_authority")
        identity = payload.get("expected_flash_identity")
        if not isinstance(identity, Mapping):
            raise ValueError("flash_identity")
        validate_identity(identity)
        if canonical_sha256(identity) != payload.get("expected_flash_identity_sha256"):
            raise ValueError("flash_identity_hash")
        report["operation_id"] = payload.get("operation_id")
        expected_project = str(payload.get("expected_project_name") or "")
        expected_target = str(payload.get("expected_target_timeline_name") or "")
        report["expected_target_timeline_name"] = expected_target
        manager = V1.safe_call(resolve, "GetProjectManager", default=None)
        project = V1.safe_call(manager, "GetCurrentProject", default=None)
        if project is None:
            raise RuntimeError("current_project")
        project_name = str(V1.safe_call(project, "GetName", default="") or "")
        report["project_name"] = project_name
        if project_name != expected_project:
            raise RuntimeError("project_identity")
        current = V1.safe_call(project, "GetCurrentTimeline", default=None)
        report["current_timeline_name"] = str(V1.safe_call(current, "GetName", default="") or "") if current is not None else None
        declared = as_int(V1.safe_call(project, "GetTimelineCount", default=0), 0)
        report["timeline_count"] = declared
        candidates: list[dict[str, Any]] = []
        target_occurrences = 0
        inspected = 0
        for timeline_index in range(1, declared + 1):
            timeline = V1.safe_call(project, "GetTimelineByIndex", timeline_index, default=None)
            if timeline is None:
                raise RuntimeError(f"timeline_missing:{timeline_index}")
            timeline_name = str(V1.safe_call(timeline, "GetName", default="") or "")
            target_occurrences += int(timeline_name == expected_target)
            video_tracks = V1.track_count(timeline, "video")
            timeline_items = 0
            for track_index in range(1, video_tracks + 1):
                items = V1.track_items(timeline, "video", track_index)
                timeline_items += len(items)
                inspected += len(items)
                for item in items:
                    row = inspect_item(timeline_name, timeline_index, track_index, item, identity)
                    if row["classification"] != "NO_FLASH_MATCH":
                        candidates.append(row)
            report["timeline_inventory"].append({"timeline_index": timeline_index, "timeline_name": timeline_name, "video_track_count": video_tracks, "video_item_count": timeline_items})
        report["expected_target_occurrence_count"] = target_occurrences
        report["inspected_video_item_count"] = inspected
        report["matches"] = candidates
        report["exact_match_count"] = sum(row["classification"] == "EXACT_FLASH_MATCH" for row in candidates)
        report["partial_match_count"] = sum(row["classification"] == "PARTIAL_FLASH_MATCH" for row in candidates)
        report["classification"] = project_classification(candidates, expected_target)
        report["ok"] = report["classification"] in CLASSIFICATIONS
    except Exception as exc:
        reason = re.sub(r"[^A-Z0-9]+", "_", str(exc).upper()).strip("_") or "UNEXPECTED_FAILURE"
        report["classification"] = f"BLOCKED_FLASH_LOCATION_PROBE_{reason}"
        report["failures"] = [f"{type(exc).__name__}: {exc}"]
    return report
