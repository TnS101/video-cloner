"""Import the calibrated Step 3D lifecycle FCPXML as a separate Resolve timeline."""
from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from typing import Any

TASK_ID = 'DZSQH7AUHJT_STEP_3D_LIFECYCLE_TIMELINE_IMPORT_V3'
MODE = "import_lifecycle_fcpxml_timeline"
EXPECTED_PROJECT = 'New Project 1'
SOURCE_TIMELINE_NAME = 'DZsqH7auhjt_textplus_full'
IMPORTED_TIMELINE_NAME = 'DZsqH7auhjt_textplus_full_step_3D_lifecycle'
FCPXML_REL = 'data/DZsqH7auhjt/davinci/DZsqH7auhjt_textplus_full_timeline_step_3D_lifecycle.fcpxml'
FCPXML_SHA256 = 'a844dc836fc0c6cd54353dee22ee7f01b90ab6500c441434b2a5a49ebe6636c0'
TARGET_WINDOWS = {
    "sub_052": [430, 452],
    "sub_057": [454, 493],
    "sub_058": [456, 492],
    "sub_081": [628, 656],
}


def safe(obj: Any, method: str, *args: Any, default: Any = None) -> Any:
    try:
        return getattr(obj, method)(*args)
    except Exception:
        return default


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def as_int(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def rational_frames(value: str, fps: int = 24) -> int:
    token = str(value or "").strip()
    if token.endswith("s"):
        token = token[:-1]
    if not token:
        raise ValueError("fcpxml_time")
    return int(Fraction(token) * fps)


def parse_fcpxml_contract(path: Path) -> dict[str, Any]:
    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        raise ValueError(f"fcpxml_parse:{exc}") from exc
    spine = next(root.iter("spine"), None)
    if spine is None:
        raise ValueError("fcpxml_spine")

    base_items: list[dict[str, Any]] = []
    caption_items: list[dict[str, Any]] = []
    transition_items: list[dict[str, Any]] = []
    for element in list(spine):
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "asset-clip" and element.get("lane") is None:
            start = rational_frames(element.get("offset") or "")
            duration = rational_frames(element.get("duration") or "")
            base_items.append({
                "name": str(element.get("name") or ""),
                "start": start,
                "end": start + duration,
            })
        elif tag == "title":
            start = rational_frames(element.get("offset") or "")
            duration = rational_frames(element.get("duration") or "")
            caption_items.append({
                "name": str(element.get("name") or ""),
                "start": start,
                "end": start + duration,
                "lane": int(element.get("lane") or 0),
            })
        elif tag == "transition":
            start = rational_frames(element.get("offset") or "")
            duration = rational_frames(element.get("duration") or "")
            transition_items.append({
                "name": str(element.get("name") or ""),
                "start": start,
                "end": start + duration,
            })

    if len(base_items) != 22:
        raise ValueError(f"fcpxml_base_count:{len(base_items)}")
    if len(caption_items) != 116:
        raise ValueError(f"fcpxml_caption_count:{len(caption_items)}")
    if len(transition_items) != 11:
        raise ValueError(f"fcpxml_transition_count:{len(transition_items)}")
    base_windows = {(row["start"], row["end"]) for row in base_items}
    caption_windows = {(row["start"], row["end"]) for row in caption_items}
    transition_windows = {(row["start"], row["end"]) for row in transition_items}
    if len(base_windows) != len(base_items):
        raise ValueError("fcpxml_duplicate_base_window")
    if len(caption_windows) != len(caption_items):
        raise ValueError("fcpxml_duplicate_caption_window")
    if len(transition_windows) != len(transition_items):
        raise ValueError("fcpxml_duplicate_transition_window")
    if base_windows & caption_windows:
        raise ValueError("fcpxml_base_caption_window_collision")
    if transition_windows & (base_windows | caption_windows):
        raise ValueError("fcpxml_transition_window_collision")
    if len({row["lane"] for row in caption_items}) != 5:
        raise ValueError("fcpxml_caption_lane_count")
    return {
        "base_items": base_items,
        "caption_items": caption_items,
        "transition_items": transition_items,
        "base_windows": base_windows,
        "caption_windows": caption_windows,
        "transition_windows": transition_windows,
    }


def item_snapshot(item: Any, track_index: int) -> dict[str, Any]:
    return {
        "track_index": track_index,
        "name": str(safe(item, "GetName", default="") or ""),
        "start": as_int(safe(item, "GetStart")),
        "end": as_int(safe(item, "GetEnd")),
    }


def timeline_name(timeline: Any) -> str:
    return str(safe(timeline, "GetName", default="") or "")


def project_timelines(project: Any) -> list[Any]:
    count = int(safe(project, "GetTimelineCount", default=0) or 0)
    return [
        timeline
        for index in range(1, count + 1)
        if (timeline := safe(project, "GetTimelineByIndex", index)) is not None
    ]


def find_timelines(project: Any, name: str) -> list[Any]:
    return [timeline for timeline in project_timelines(project) if timeline_name(timeline) == name]


def track_rows(timeline: Any, track_type: str) -> list[dict[str, Any]]:
    count = int(safe(timeline, "GetTrackCount", track_type, default=0) or 0)
    rows = []
    for index in range(1, count + 1):
        items = list(safe(timeline, "GetItemListInTrack", track_type, index, default=[]) or [])
        rows.append({
            "track_index": index,
            "item_count": len(items),
            "items": [item_snapshot(item, index) for item in items],
        })
    return rows


def timeline_snapshot(timeline: Any) -> dict[str, Any]:
    video = track_rows(timeline, "video")
    audio = track_rows(timeline, "audio")
    return {
        "name": timeline_name(timeline),
        "video_track_count": len(video),
        "audio_track_count": len(audio),
        "video_item_counts": [row["item_count"] for row in video],
        "audio_item_counts": [row["item_count"] for row in audio],
        "video_items": [item for row in video for item in row["items"]],
        "audio_items": [item for row in audio for item in row["items"]],
    }


def target_match(rows: list[dict[str, Any]], cue_id: str, window: list[int]) -> dict[str, Any]:
    matches = [
        row for row in rows
        if row.get("start") == window[0] and row.get("end") == window[1]
    ]
    if len(matches) != 1:
        raise ValueError(f"target_identity:{cue_id}:{len(matches)}")
    return matches[0]


def validate_imported_timeline(timeline: Any, fcpxml_path: Path) -> dict[str, Any]:
    snapshot = timeline_snapshot(timeline)
    if snapshot["name"] != IMPORTED_TIMELINE_NAME:
        raise ValueError("imported_timeline_name")
    if snapshot["audio_track_count"] < 1:
        raise ValueError("audio_track_count")

    contract = parse_fcpxml_contract(fcpxml_path)
    live_rows = list(snapshot["video_items"])
    by_window: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in live_rows:
        window = (row.get("start"), row.get("end"))
        if None in window:
            raise ValueError("live_item_window_missing")
        by_window.setdefault(window, []).append(row)

    def resolve_expected(
        expected_rows: list[dict[str, Any]],
        kind: str,
    ) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        for expected in expected_rows:
            window = (expected["start"], expected["end"])
            matches = by_window.get(window, [])
            if len(matches) != 1:
                raise ValueError(
                    f"{kind}_window_match:{expected['start']}:{expected['end']}:{len(matches)}"
                )
            resolved.append(matches[0])
        return resolved

    base_rows = resolve_expected(contract["base_items"], "base")
    caption_rows = resolve_expected(contract["caption_items"], "caption")
    matched_ids = {id(row) for row in base_rows + caption_rows}
    unmatched_rows = [row for row in live_rows if id(row) not in matched_ids]

    def normalized_name(value: Any) -> str:
        return " ".join(str(value or "").casefold().split())

    transition_rows: list[dict[str, Any]] = []
    available = list(unmatched_rows)
    for expected in contract["transition_items"]:
        expected_name = normalized_name(expected.get("name"))
        candidates = []
        for row in available:
            start = row.get("start")
            end = row.get("end")
            if start is None or end is None:
                continue
            distance = abs(start - expected["start"]) + abs(end - expected["end"])
            if distance > 2:
                continue
            live_name = normalized_name(row.get("name"))
            name_penalty = 0 if not live_name or live_name == expected_name else 1
            candidates.append((name_penalty, distance, row))
        candidates.sort(key=lambda item: (item[0], item[1]))
        if not candidates:
            raise ValueError(
                f"transition_window_match:{expected['start']}:{expected['end']}:0"
            )
        best_penalty, best_distance, best_row = candidates[0]
        tied = [item for item in candidates if item[:2] == (best_penalty, best_distance)]
        if len(tied) != 1:
            raise ValueError(
                f"transition_window_match:{expected['start']}:{expected['end']}:{len(tied)}"
            )
        transition_rows.append(best_row)
        available.remove(best_row)

    if available:
        raise ValueError(f"unexpected_video_items:{len(available)}")

    base_tracks = sorted({int(row["track_index"]) for row in base_rows})
    caption_tracks = sorted({int(row["track_index"]) for row in caption_rows})
    transition_tracks = sorted({int(row["track_index"]) for row in transition_rows})
    if len(base_rows) != 22:
        raise ValueError(f"base_video_item_count:{len(base_rows)}")
    if len(base_tracks) != 1:
        raise ValueError(f"base_video_track_count:{len(base_tracks)}")
    if len(transition_rows) != 11:
        raise ValueError(f"transition_item_count:{len(transition_rows)}")
    if transition_tracks != base_tracks:
        raise ValueError(f"transition_track_identity:{transition_tracks}")
    if len(caption_rows) != 116:
        raise ValueError(f"caption_item_count:{len(caption_rows)}")
    if len(caption_tracks) != 5:
        raise ValueError(f"caption_lane_count:{len(caption_tracks)}")
    if set(base_tracks) & set(caption_tracks):
        raise ValueError("base_caption_track_overlap")

    targets = {
        cue_id: target_match(caption_rows, cue_id, window)
        for cue_id, window in TARGET_WINDOWS.items()
    }
    return {
        "ok": True,
        "timeline_name": snapshot["name"],
        "video_track_count": snapshot["video_track_count"],
        "audio_track_count": snapshot["audio_track_count"],
        "base_video_item_count": len(base_rows),
        "base_video_track_indices": base_tracks,
        "transition_item_count": len(transition_rows),
        "transition_track_indices": transition_tracks,
        "caption_item_count": len(caption_rows),
        "caption_lane_count": len(caption_tracks),
        "caption_track_indices": caption_tracks,
        "unmatched_video_item_count": 0,
        "target_results": {
            cue_id: {
                "actual_window": [row["start"], row["end"]],
                "expected_window": TARGET_WINDOWS[cue_id],
                "matched": [row["start"], row["end"]] == TARGET_WINDOWS[cue_id],
                "track_index": row["track_index"],
                "name": row["name"],
            }
            for cue_id, row in targets.items()
        },
        "snapshot": snapshot,
    }


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    report: dict[str, Any] = {
        "ok": False,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "classification": None,
        "import_call_count": 0,
        "timeline_created": False,
        "source_timeline_modified": None,
        "current_timeline_selected": False,
        "save_call_count": 0,
        "failures": [],
    }
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        if (
            command.get("task") != TASK_ID
            or command.get("run_id") != run_id
            or command.get("mode") != MODE
        ):
            raise ValueError("command_identity")
        if payload.get("import_permitted") is not True:
            raise ValueError("import_not_authorized")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        output_dir = root / str(payload.get("report_dir") or "")
        output_dir.mkdir(parents=True, exist_ok=True)
        fcpxml_path = root / str(payload.get("fcpxml_path") or "")
        if not fcpxml_path.is_file() or sha256(fcpxml_path) != FCPXML_SHA256:
            raise ValueError("fcpxml_identity")

        manager = safe(resolve, "GetProjectManager")
        project = safe(manager, "GetCurrentProject")
        if project is None or str(safe(project, "GetName", default="") or "") != EXPECTED_PROJECT:
            raise ValueError("project_identity")
        media_pool = safe(project, "GetMediaPool")
        if media_pool is None:
            raise ValueError("media_pool_missing")

        source_matches = find_timelines(project, SOURCE_TIMELINE_NAME)
        if len(source_matches) != 1:
            raise ValueError(f"source_timeline_identity:{len(source_matches)}")
        source_before = timeline_snapshot(source_matches[0])
        timeline_names_before = [timeline_name(item) for item in project_timelines(project)]
        existing = find_timelines(project, IMPORTED_TIMELINE_NAME)

        if len(existing) > 1:
            raise ValueError("duplicate_imported_timeline")
        if len(existing) == 1:
            imported = existing[0]
            classification = "ALREADY_IMPORTED_MATCHED"
        else:
            imported_result = safe(media_pool, "ImportTimelineFromFile", str(fcpxml_path))
            report["import_call_count"] = 1
            report["timeline_created"] = True
            matches = find_timelines(project, IMPORTED_TIMELINE_NAME)
            if len(matches) != 1:
                raise ValueError(f"import_result_identity:{len(matches)}")
            imported = matches[0]
            if imported_result not in (None, False, True) and timeline_name(imported_result):
                if timeline_name(imported_result) != IMPORTED_TIMELINE_NAME:
                    raise ValueError("returned_timeline_identity")
            classification = "NEW_TIMELINE_IMPORTED"

        imported_validation = validate_imported_timeline(imported, fcpxml_path)
        write_json(output_dir / "imported_timeline_snapshot.json", imported_validation)

        source_after_matches = find_timelines(project, SOURCE_TIMELINE_NAME)
        if len(source_after_matches) != 1:
            raise ValueError("source_timeline_missing_after")
        source_after = timeline_snapshot(source_after_matches[0])
        source_unchanged = source_after == source_before
        if not source_unchanged:
            raise ValueError("source_timeline_changed")

        current_before = timeline_name(safe(project, "GetCurrentTimeline"))
        current_set = bool(safe(project, "SetCurrentTimeline", imported, default=False))
        current_after = timeline_name(safe(project, "GetCurrentTimeline"))
        if current_after != IMPORTED_TIMELINE_NAME:
            raise ValueError("current_timeline_selection")
        report["current_timeline_selected"] = current_set or current_before == IMPORTED_TIMELINE_NAME

        timeline_names_after = [timeline_name(item) for item in project_timelines(project)]
        expected_delta = 0 if classification == "ALREADY_IMPORTED_MATCHED" else 1
        actual_delta = len(timeline_names_after) - len(timeline_names_before)
        if actual_delta != expected_delta:
            raise ValueError(f"timeline_count_delta:{actual_delta}")

        protection = {
            "ok": True,
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "source_timeline_unchanged": True,
            "source_before": source_before,
            "source_after": source_after,
            "timeline_names_before": timeline_names_before,
            "timeline_names_after": timeline_names_after,
            "timeline_count_delta": actual_delta,
            "expected_timeline_count_delta": expected_delta,
            "save_call_count": 0,
        }
        write_json(output_dir / "source_timeline_protection.json", protection)
        write_json(output_dir / "timeline_import_result.json", {
            "ok": True,
            "task_id": TASK_ID,
            "run_id": run_id,
            "classification": classification,
            "fcpxml_path": str(fcpxml_path),
            "fcpxml_sha256": FCPXML_SHA256,
            "import_call_count": report["import_call_count"],
            "timeline_created": report["timeline_created"],
            "imported_timeline_name": IMPORTED_TIMELINE_NAME,
            "current_timeline_name": current_after,
            "visual_approval_required": True,
        })

        report.update({
            "ok": True,
            "classification": classification,
            "imported_timeline_name": IMPORTED_TIMELINE_NAME,
            "current_timeline_name": current_after,
            "source_timeline_modified": False,
            "caption_item_count": imported_validation["caption_item_count"],
            "caption_lane_count": imported_validation["caption_lane_count"],
            "base_video_item_count": imported_validation["base_video_item_count"],
            "base_video_track_indices": imported_validation["base_video_track_indices"],
            "transition_item_count": imported_validation["transition_item_count"],
            "transition_track_indices": imported_validation["transition_track_indices"],
            "caption_track_indices": imported_validation["caption_track_indices"],
            "target_results": imported_validation["target_results"],
            "visual_approval_required": True,
            "next_boundary": "Visually compare the imported lifecycle timeline against the original timeline before acceptance.",
        })
    except Exception as exc:
        report["failures"] = [f"{type(exc).__name__}: {exc}"]
    return report
