"""Roll out the accepted OSS-002 animation plan to the 15 remaining captions."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


MODULE_DIR = Path(__file__).resolve().parent


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot_load:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


canary = _load("vc_oss002_proven_canary", MODULE_DIR / "oss002_sub008_production_canary.py")

TASK_ID = "OSS002_16_CAPTION_BATCH_ROLLOUT_V1"
MODE = "oss002_16_caption_batch_rollout"
PROJECT_NAME = canary.PROJECT_NAME
TARGET_TIMELINE = canary.TARGET_TIMELINE
EXPECTED_RESOLVE_VERSION = canary.EXPECTED_RESOLVE_VERSION
EXPECTED_CAPTIONS = 112
EXPECTED_SELECTED = 16
ACCEPTED_ORDINAL = 8
ACCEPTED_SOURCE_NAME = "_VC_OSS002_SUB008_01093b6b3bcb"
ACCEPTED_SOURCE_UID = "03228b6b-cb9e-42ad-b314-d6ac9486da3d"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repository_file(root: Path, value: object, expected_hash: object, label: str) -> Path:
    path = (root / str(value or "")).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label}_outside_repository") from exc
    if not path.is_file() or _sha256(path) != expected_hash:
        raise ValueError(f"{label}_identity")
    return path


def selected_targets(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for item in payload.get("items") or []:
        if item.get("selected") is not True:
            continue
        animation = item.get("animation") or {}
        row = {
            "ordinal": int(item["cue_index"]),
            "cue_id": str(item["cue_id"]),
            "text": str(item["text"]),
            "start": int(item["start_frame"]),
            "duration": int(item["duration_frames"]),
            "end": int(item["end_frame"]),
            "family": str(animation.get("animation_type") or ""),
            "source_event_id": str(animation.get("source_event_id") or ""),
            "keyframes": list(animation.get("keyframes") or []),
        }
        if row["end"] - row["start"] != row["duration"] or row["family"] not in {"slide", "scale"} or not row["keyframes"]:
            raise ValueError(f"animation_plan_target:{row['cue_id']}")
        rows.append(row)
    rows.sort(key=lambda row: row["ordinal"])
    families = {name: sum(row["family"] == name for row in rows) for name in ("slide", "scale")}
    if len(rows) != EXPECTED_SELECTED or families != {"slide": 6, "scale": 10} or [row["ordinal"] for row in rows].count(ACCEPTED_ORDINAL) != 1:
        raise ValueError("animation_plan_selection")
    return rows


def remaining_targets(path: Path) -> list[dict[str, Any]]:
    return [row for row in selected_targets(path) if row["ordinal"] != ACCEPTED_ORDINAL]


def _styles_by_ordinal(path: Path) -> dict[int, dict[str, Any]]:
    root = ET.parse(path).getroot()
    titles = list(root.findall("./library/event/project/sequence/spine/title"))
    formats = list(root.findall("./resources/format"))
    if len(titles) != EXPECTED_CAPTIONS or len(formats) != 1:
        raise ValueError("fcpxml_caption_contract")
    width = int(formats[0].get("width") or 0)
    if width <= 0:
        raise ValueError("fcpxml_width")
    styles = {}
    for ordinal, title in enumerate(titles, start=1):
        text_node = title.find("./text/text-style")
        style_node = title.find("./text-style-def/text-style")
        if text_node is None or style_node is None:
            raise ValueError(f"fcpxml_style:{ordinal}")

        def color(name: str, default: str = "0 0 0 0") -> list[float]:
            values = [float(value) for value in str(style_node.get(name) or default).split()]
            if len(values) != 4:
                raise ValueError(f"fcpxml_color:{ordinal}:{name}")
            return values

        font_size = float(style_node.get("fontSize") or 0)
        if font_size <= 0:
            raise ValueError(f"fcpxml_font_size:{ordinal}")
        stroke_width = float(style_node.get("strokeWidth") or 0)
        shadow_offset = float(style_node.get("shadowOffset") or 0)
        fill, outline, shadow = color("fontColor"), color("strokeColor"), color("shadowColor")
        styles[ordinal] = {
            "StyledText": str(text_node.text or ""),
            "Font": str(style_node.get("font") or "Arial"),
            "Style": "Bold" if style_node.get("bold") == "1" else "Regular",
            "Size": max(0.02, font_size / width * 1.5),
            "Center": [0.5, 0.5],
            "Enabled1": 1.0,
            "Red1": fill[0], "Green1": fill[1], "Blue1": fill[2], "Alpha1": fill[3],
            "Enabled2": 1.0, "ElementShape2": 1.0,
            "Red2": outline[0], "Green2": outline[1], "Blue2": outline[2], "Alpha2": outline[3],
            "Thickness2": stroke_width / font_size, "OutsideOnly2": 1.0,
            "Enabled3": 1.0, "ElementShape3": 0.0,
            "Red3": shadow[0], "Green3": shadow[1], "Blue3": shadow[2], "Alpha3": shadow[3],
            "Offset3": [shadow_offset / width, shadow_offset / width],
        }
    return styles


def animation_payload(target: dict[str, Any], style: dict[str, Any]) -> dict[str, Any]:
    family = target["family"]
    if family == "slide":
        center = style["Center"]
        values = [[center[0] + float(row["center_offset"][0]), center[1] + float(row["center_offset"][1])] for row in target["keyframes"]]
        property_name = "Center"
    else:
        values = [float(style["Size"]) * float(row["size_multiplier"]) for row in target["keyframes"]]
        property_name = "Size"
    return {
        "authority": "visual_observed",
        "source_evidence_id": target["source_event_id"],
        "source_type": family,
        "property": property_name,
        "keyframes": [
            {"frame": int(row["frame"]), "relative_time": float(row["relative_time"]), "value": value}
            for row, value in zip(target["keyframes"], values)
        ],
    }


def allocate_tracks(targets: list[dict[str, Any]], occupied: dict[int, list[tuple[int, int]]]) -> dict[int, int]:
    schedule = {track: list(intervals) for track, intervals in occupied.items() if track >= 3}
    schedule.setdefault(3, [])
    allocation = {}
    for target in sorted(targets, key=lambda row: (row["start"], row["ordinal"])):
        interval = (target["start"], target["end"])
        track = 3
        while any(interval[0] < end and start < interval[1] for start, end in schedule.setdefault(track, [])):
            track += 1
        schedule[track].append(interval)
        allocation[target["ordinal"]] = track
    return allocation


def _source_name(target: dict[str, Any], run_id: str) -> str:
    token = str(run_id).rsplit("_", 1)[-1][:12]
    return f"_VC_OSS002_SUB{target['ordinal']:03d}_{token}"


def _nested_items(timeline: Any) -> list[dict[str, Any]]:
    rows = []
    count = int(canary._optional(timeline, "GetTrackCount", "video", default=0) or 0)
    for track in range(3, count + 1):
        for item in canary._optional(timeline, "GetItemListInTrack", "video", track, default=[]) or []:
            pool_item = canary._optional(item, "GetMediaPoolItem")
            inner = canary._optional(pool_item, "GetTimeline")
            if inner is not None:
                rows.append({"item": item, "track": track, "start": canary._item_start(item), "duration": canary._item_duration(item), "inner": inner, "source": canary._timeline_identity(inner)})
    return rows


def _accepted_sub008(timeline: Any, base_frame: int) -> dict[str, Any]:
    matches = [row for row in _nested_items(timeline) if row["source"] == {"name": ACCEPTED_SOURCE_NAME, "unique_id": ACCEPTED_SOURCE_UID}]
    if len(matches) != 1:
        raise ValueError(f"accepted_sub008_replacement:{len(matches)}")
    row = matches[0]
    if row["track"] != 3 or row["start"] - base_frame != 39 or row["duration"] != 5:
        raise ValueError("accepted_sub008_placement")
    return row


def _non_target_snapshot(rows: list[dict[str, Any]], base_frame: int, selected_ordinals: set[int]) -> list[tuple[Any, ...]]:
    if len(rows) != EXPECTED_CAPTIONS:
        raise ValueError(f"basic_title_count:{len(rows)}")
    return [
        (ordinal, row["start"] - base_frame, row["duration"], row["enabled"])
        for ordinal, row in enumerate(rows, start=1) if ordinal not in selected_ordinals
    ]


def _direction(target: dict[str, Any]) -> str:
    first = target["keyframes"][0]
    if target["family"] == "scale":
        return "scale_up_to_1.0" if float(first["size_multiplier"]) < 1.0 else "scale_down_to_1.0"
    x, y = (float(value) for value in first["center_offset"])
    if abs(x) >= abs(y):
        return "from_left_to_center" if x < 0 else "from_right_to_center"
    return "from_top_to_center" if y < 0 else "from_bottom_to_center"


def review_manifest(targets: list[dict[str, Any]], allocations: dict[int, int], status: str) -> dict[str, Any]:
    rows = []
    for target in targets:
        rows.append({
            "ordinal": target["ordinal"], "cue_id": target["cue_id"], "text": target["text"],
            "relative_start": target["start"], "duration": target["duration"], "animation_family": target["family"],
            "expected_direction": _direction(target), "replacement_track": allocations.get(target["ordinal"], 3),
            "technical_status": "HUMAN_ACCEPTED_FIDELITY_APPROXIMATE" if target["ordinal"] == ACCEPTED_ORDINAL else status,
            "human_review": {"classification_correct": None, "direction_correct": None, "timing_correct": None, "magnitude_correct": None, "false_positive": None, "notes": ""},
        })
    return {
        "schema": "oss002_caption_batch_human_review",
        "targets": rows,
        "decision_rule": {
            "acceptable": "KEEP existing analysis and proceed to OSS-003 transitions",
            "systematic_weakness": "benchmark proven references including HyperFrames against the same timestamps and human ground truth, then KEEP/ADAPT/COMBINE/REPLACE",
        },
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _rollback(project: Any, pool: Any, sources: list[Any], placed: list[Any], hide_attempted: list[int], created_tracks: list[int]) -> dict[str, Any]:
    restored = []
    replacements_deleted = placed == []
    sources_deleted = sources == []
    tracks_removed = created_tracks == []
    try:
        target = canary._activate_target(project)
        rows = canary.basic_title_rows(target)
        for ordinal in hide_attempted:
            item = rows[ordinal - 1]["item"]
            returned = canary._optional(item, "SetClipEnabled", True, default=False)
            restored.append(returned is not False and canary._clip_enabled(item) is True)
        if placed:
            replacements_deleted = canary._optional(target, "DeleteClips", placed, False, default=False) is True
        tracks_removed = True
        for track in sorted(created_tracks, reverse=True):
            items = canary._optional(target, "GetItemListInTrack", "video", track)
            tracks_removed = tracks_removed and isinstance(items, (list, tuple)) and not items and canary._optional(target, "DeleteTrack", "video", track, default=False) is True
        canary._optional(project, "SetCurrentTimeline", target, default=False)
        if sources:
            sources_deleted = canary._optional(pool, "DeleteTimelines", sources, default=False) is True
    except Exception:
        pass
    originals_restored = len(restored) == len(hide_attempted) and all(restored)
    return {
        "originals_restored": originals_restored,
        "restored_count": sum(restored),
        "replacement_items_deleted": replacements_deleted,
        "source_timelines_deleted": sources_deleted,
        "created_tracks_removed": tracks_removed,
        "ok": originals_restored and replacements_deleted and sources_deleted and tracks_removed,
    }


def run(resolve: Any, context: dict[str, Any]) -> dict[str, Any]:
    run_id = str(context.get("run_id") or "")
    result: dict[str, Any] = {"ok": False, "task_id": TASK_ID, "mode": MODE, "run_id": run_id, "save_project_called": False, "failures": []}
    project = pool = target_timeline = None
    created_sources: list[Any] = []
    placed_items: list[Any] = []
    hide_attempted: list[int] = []
    created_tracks: list[int] = []
    saved = False
    try:
        command = context.get("command") or {}
        payload = command.get("payload") or {}
        required = {
            "expected_project": PROJECT_NAME,
            "target_timeline": TARGET_TIMELINE,
            "accepted_sub008_source_name": ACCEPTED_SOURCE_NAME,
            "accepted_sub008_source_uid": ACCEPTED_SOURCE_UID,
            "expected_selected_count": EXPECTED_SELECTED,
            "remaining_target_count": EXPECTED_SELECTED - 1,
            "save_after_batch_verification": True,
        }
        if command.get("task") != TASK_ID or command.get("mode") != MODE or command.get("run_id") != run_id or any(payload.get(key) != value for key, value in required.items()):
            raise ValueError("command_authority")
        result["resolve_version"] = str(canary.carrier._call(resolve, "GetVersionString") or "")
        if result["resolve_version"] != EXPECTED_RESOLVE_VERSION:
            raise ValueError(f"resolve_version:{result['resolve_version']}")
        root = Path(str(payload.get("repository_root") or "")).resolve()
        if not (root / "AGENTS.md").is_file():
            raise ValueError("repository_identity")
        plan_path = _repository_file(root, payload.get("animation_plan_path"), payload.get("animation_plan_sha256"), "animation_plan")
        fcpxml_path = _repository_file(root, payload.get("fcpxml_path"), payload.get("fcpxml_sha256"), "fcpxml")
        targets = selected_targets(plan_path)
        remaining = [row for row in targets if row["ordinal"] != ACCEPTED_ORDINAL]
        styles = _styles_by_ordinal(fcpxml_path)
        manager = canary.carrier._call(resolve, "GetProjectManager")
        project = canary.carrier._call(manager, "GetCurrentProject")
        if project is None or canary._name(project) != PROJECT_NAME:
            raise ValueError(f"project_identity:{canary._name(project) if project else ''}")
        pool = canary.carrier._call(project, "GetMediaPool")
        target_timeline = canary._activate_target(project)
        base_frame = int(canary.carrier._call(target_timeline, "GetStartFrame") or 0)
        captions = canary.basic_title_rows(target_timeline)
        if len(captions) != EXPECTED_CAPTIONS:
            raise ValueError(f"basic_title_count:{len(captions)}")
        accepted = _accepted_sub008(target_timeline, base_frame)
        if captions[ACCEPTED_ORDINAL - 1]["enabled"] is not False:
            raise ValueError("accepted_sub008_original_enabled")
        selected_ordinals = {row["ordinal"] for row in targets}
        non_targets_before = _non_target_snapshot(captions, base_frame, selected_ordinals)
        for row in remaining:
            source = captions[row["ordinal"] - 1]
            if source["start"] - base_frame != row["start"] or source["duration"] != row["duration"] or source["enabled"] is not True:
                raise ValueError(f"source_caption_contract:{row['cue_id']}")
            if source["text_readback"] is not None and source["text_readback"] != row["text"]:
                raise ValueError(f"source_caption_text:{row['cue_id']}")
            if styles[row["ordinal"]]["StyledText"] != row["text"]:
                raise ValueError(f"fcpxml_caption_text:{row['cue_id']}")

        occupied = {}
        track_count_before = int(canary.carrier._call(target_timeline, "GetTrackCount", "video") or 0)
        for track in range(3, track_count_before + 1):
            occupied[track] = [
                (canary._item_start(item) - base_frame, canary._item_start(item) - base_frame + canary._item_duration(item))
                for item in canary._optional(target_timeline, "GetItemListInTrack", "video", track, default=[]) or []
            ]
        allocation = allocate_tracks(remaining, occupied)
        max_track = max(allocation.values(), default=3)
        while int(canary.carrier._call(target_timeline, "GetTrackCount", "video") or 0) < max_track:
            if canary.carrier._call(target_timeline, "AddTrack", "video") is not True:
                raise RuntimeError("overlay_track_create")
            created_tracks.append(int(canary.carrier._call(target_timeline, "GetTrackCount", "video") or 0))
        existing_names = {row["name"] for row in canary._timeline_inventory(project)}
        source_names = {row["ordinal"]: _source_name(row, run_id) for row in remaining}
        if len(set(source_names.values())) != len(source_names) or any(name in existing_names for name in source_names.values()):
            raise ValueError("batch_source_timeline_collision")

        technical_rows = []
        for row in remaining:
            style = styles[row["ordinal"]]
            source_name = source_names[row["ordinal"]]
            source_timeline = canary.carrier._call(pool, "CreateEmptyTimeline", source_name)
            created_sources.append(source_timeline)
            source_identity = canary._timeline_identity(source_timeline)
            if source_timeline is None or source_identity["name"] != source_name or not source_identity["unique_id"] or canary.carrier._call(project, "SetCurrentTimeline", source_timeline) is not True:
                raise RuntimeError(f"source_timeline_create:{row['cue_id']}")
            canary.carrier._call(source_timeline, "InsertFusionTitleIntoTimeline", "Text+")
            _, tool = canary.carrier._find_textplus(source_timeline)
            static_result = canary._set_static_style(tool, style)
            comp = canary.carrier._call((canary.carrier._find_textplus(source_timeline))[0], "GetFusionCompByIndex", 1)
            animation_spec = animation_payload(row, style)
            animation_result = canary.animation.apply_authorized_animation(comp, tool, animation_spec, row["duration"])
            source_item = canary.carrier._call(source_timeline, "GetMediaPoolItem")
            target_timeline = canary._activate_target(project)
            returned = canary.carrier._call(pool, "AppendToTimeline", [{
                "mediaPoolItem": source_item,
                "startFrame": 0,
                "endFrame": row["duration"],
                "trackIndex": allocation[row["ordinal"]],
                "recordFrame": base_frame + row["start"],
            }])
            if not isinstance(returned, (list, tuple)) or len(returned) != 1 or returned[0] is None:
                raise RuntimeError(f"replacement_append:{row['cue_id']}")
            placed = returned[0]
            placed_items.append(placed)
            track_type, track_index = canary.carrier._call(placed, "GetTrackTypeAndIndex")
            placement = {"track_type": track_type, "track": int(track_index), "start": canary._item_start(placed) - base_frame, "duration": canary._item_duration(placed)}
            expected = {"track_type": "video", "track": allocation[row["ordinal"]], "start": row["start"], "duration": row["duration"]}
            if placement != expected:
                raise RuntimeError(f"replacement_placement:{row['cue_id']}:{placement!r}")
            inner = canary.carrier._call(canary.carrier._call(placed, "GetMediaPoolItem"), "GetTimeline")
            if inner is None or canary.carrier._timeline_key(inner) != canary.carrier._timeline_key(source_timeline):
                raise RuntimeError(f"replacement_inner_timeline:{row['cue_id']}")
            _, inner_tool = canary.carrier._find_textplus(inner)
            animated_input = animation_spec["property"]
            if any(not canary._matches(canary.animation.read_input(inner_tool, name, 0), value) for name, value in style.items() if name != animated_input):
                raise RuntimeError(f"replacement_style_readback:{row['cue_id']}")
            targets_readback = [{"input": animated_input, "local_frame": int(key["frame"]), "expected": key["value"]} for key in animation_spec["keyframes"]]
            if not canary.animation.input_targets_are_correct(inner_tool, animated_input, targets_readback):
                raise RuntimeError(f"replacement_animation_readback:{row['cue_id']}")
            refreshed = canary.basic_title_rows(target_timeline)
            original = refreshed[row["ordinal"] - 1]["item"]
            hide_attempted.append(row["ordinal"])
            hidden_return = canary.carrier._call(original, "SetClipEnabled", False)
            if hidden_return is False or canary._clip_enabled(original) is not False:
                raise RuntimeError(f"source_caption_disable:{row['cue_id']}")
            technical_rows.append({
                "ordinal": row["ordinal"], "cue_id": row["cue_id"], "text": row["text"], "family": row["family"],
                "placement": placement, "source_timeline": source_identity, "animation": animation_result, "static_style": static_result["ok"], "technical_status": "PASS",
            })

        target_timeline = canary._activate_target(project)
        captions_after = canary.basic_title_rows(target_timeline)
        if _non_target_snapshot(captions_after, base_frame, selected_ordinals) != non_targets_before:
            raise RuntimeError("non_target_captions_changed")
        if any(captions_after[ordinal - 1]["enabled"] is not False for ordinal in selected_ordinals):
            raise RuntimeError("selected_originals_not_disabled")
        _accepted_sub008(target_timeline, base_frame)
        nested_after = _nested_items(target_timeline)
        created_keys = {canary.carrier._timeline_key(source) for source in created_sources}
        if {canary.carrier._timeline_key(row["inner"]) for row in nested_after if canary.carrier._timeline_key(row["inner"]) in created_keys} != created_keys:
            raise RuntimeError("batch_replacements_missing")

        manifest_path = (root / str(payload.get("review_manifest_path") or "")).resolve()
        manifest_path.relative_to(root)
        manifest = review_manifest(targets, {ACCEPTED_ORDINAL: accepted["track"], **allocation}, "TECHNICAL_PASS")
        manifest.update({"run_id": run_id, "project": PROJECT_NAME, "timeline": TARGET_TIMELINE, "production_saved": False})
        _write_json(manifest_path, manifest)
        save_returned = canary.carrier._call(manager, "SaveProject")
        result["save_project_called"] = True
        result["save_project_returned"] = save_returned
        if save_returned is not True:
            raise RuntimeError("save_project_failed")
        saved = True
        manifest["production_saved"] = True
        try:
            _write_json(manifest_path, manifest)
            manifest_written = True
        except Exception:
            manifest_written = False
        result.update({
            "ok": True,
            "accepted_sub008": {"status": "HUMAN_ACCEPTED_FIDELITY_APPROXIMATE", "source": accepted["source"], "placement": {"track": accepted["track"], "start": accepted["start"] - base_frame, "duration": accepted["duration"]}},
            "remaining_target_count": len(remaining),
            "track_allocation": {str(key): value for key, value in allocation.items()},
            "created_source_timeline_count": len(created_sources),
            "created_track_count": len(created_tracks),
            "technical_rows": technical_rows,
            "review_manifest_path": str(manifest_path),
            "review_manifest_written": manifest_written,
        })
    except Exception as exc:
        result["failures"].append(f"{type(exc).__name__}: {exc}")
        if not saved and project is not None and pool is not None:
            result["rollback"] = _rollback(project, pool, created_sources, placed_items, hide_attempted, created_tracks)
    return result
