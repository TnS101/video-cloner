"""Build the complete Step 3D editable Text+ lifecycle timeline.

This module uses the only live-proven Resolve route:

    MediaPool.AppendToTimeline -> TimelineItem.ImportFusionComp

The protected ``DZsqH7auhjt_textplus_full`` timeline is treated as read-only and
is used only for base timeline duplication plus Fusion/style exports.  The
calibrated lifecycle authority supplies target windows.  Dense visual tracking
is used only where it proves that multiple transcript cues are one persistent
visual instance.  The current accepted data proves exactly one such merge:
``sub_051`` + ``sub_054`` -> one lower-case ``they`` instance.

On PASS a new complete timeline is retained for visual review.  On any failure
it is deleted and the original timeline/page are restored.  No fallback Resolve
API and no second runtime attempt are used.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

VISUAL_BASE_PATH = Path(__file__).with_name("step_3D_visual_instance_correction.py")
_spec = importlib.util.spec_from_file_location("vc_visual_instance_correction_v3", VISUAL_BASE_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot_load:{VISUAL_BASE_PATH}")
visual = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = visual
_spec.loader.exec_module(visual)
media = visual.media
base = visual.base

TASK_ID = "DZSQH7AUHJT_STEP_3D_FULL_LIFECYCLE_TEXTPLUS_ROLLOUT_V6"
MODE = "STEP_3D_FULL_LIFECYCLE_TEXTPLUS_ROLLOUT"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3D_full_lifecycle_textplus_rollout.py"
SOURCE_TIMELINE_NAME = base.SOURCE_TIMELINE_NAME
FINAL_TIMELINE_NAME = "DZsqH7auhjt_textplus_full_step_3D_complete_v6_exact_lifecycles"
EXPECTED_SOURCE_CAPTION_COUNT = 116
EXPECTED_INSTANCE_COUNT = 115
EXPECTED_ALIAS_COVERAGE = 116
EXPECTED_LANE_COUNT = 5
EXPECTED_ANIMATED_COUNT = 8
CAPTION_TRACK_BASE = 3
APPEND_BATCH_SIZE = 8
MIN_APPEND_SOURCE_DURATION = 2
APPEND_SOURCE_END_PADDING_FRAMES = 1
EXPECTED_ONE_FRAME_CARRIER_IDS = ("sub_073",)
EXPECTED_BASE_COLLISION_RELOCATION_IDS = ("sub_052",)
EXPECTED_RUNTIME_CARRIER_TRACK_USAGE = {"3": 71, "4": 21, "5": 16, "6": 5, "7": 2}
ACCEPTED_STATE_RELATIVE_PATH = base.ACCEPTED_STATE_RELATIVE_PATH
SOURCE_HASH_ALGORITHM = base.SOURCE_HASH_ALGORITHM
SOURCE_RANGE_POLICY = "exact_or_resolve_end_shortened_up_to_2_frames"
BASE_INVENTORY_STABLE_FIELDS = (
    "name",
    "track_index",
    "start",
    "end",
    "duration",
    "media_pool_item_name",
)

LIFECYCLE_AUTHORITY_RELATIVE_PATH = (
    "data/DZsqH7auhjt/analysis/"
    "DZsqH7auhjt_caption_lifecycle_authority_step_3D_calibrated.json"
)
WORD_TRACKS_RELATIVE_PATH = visual.WORD_TRACKS_RELATIVE_PATH
LIFECYCLE_REDETECTION_RELATIVE_PATH = visual.LIFECYCLE_REDETECTION_RELATIVE_PATH
ANIMATION_TARGETS_RELATIVE_PATH = (
    "data/DZsqH7auhjt/analysis/"
    "DZsqH7auhjt_caption_animation_step_3C_source_targets.json"
)
SOURCE_CONTROLLER_REPORT_RELATIVE_PATH = (
    "data/DZsqH7auhjt/davinci/DZsqH7auhjt_resolve_controller_report.json"
)

SIGNATURE_POINT_INPUTS = ("Center",)
SIGNATURE_SCALAR_INPUTS = (
    "Size",
    "Red1",
    "Green1",
    "Blue1",
    "Alpha1",
    "Enabled2",
    "Thickness2",
    "Enabled3",
    "Opacity1",
    "Opacity2",
    "Opacity3",
)


def load_json(path: Path) -> Dict[str, Any]:
    return visual.load_json(path)


def cue_number(cue_id: str) -> int:
    try:
        return int(str(cue_id).split("_")[-1])
    except (TypeError, ValueError):
        raise ValueError(f"cue_id:{cue_id}")


def animation_map(document: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    items = document.get("items") if isinstance(document.get("items"), list) else []
    rows: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("animation_item")
        cue_id = str(item.get("cue_id") or "")
        if not cue_id or cue_id in rows:
            raise ValueError(f"animation_cue:{cue_id}")
        targets = item.get("targets") if isinstance(item.get("targets"), list) else []
        if len(targets) != 2:
            raise ValueError(f"animation_targets:{cue_id}")
        rows[cue_id] = dict(item)
    return rows


def controller_item_map(document: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    applier = document.get("caption_textplus_applier")
    if not isinstance(applier, dict):
        raise ValueError("controller_caption_applier")
    items = applier.get("items") if isinstance(applier.get("items"), list) else []
    rows: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("controller_item")
        cue_id = str(item.get("cue_id") or "")
        if not cue_id or cue_id in rows:
            raise ValueError(f"controller_cue:{cue_id}")
        rows[cue_id] = dict(item)
    return rows


def accepted_tracks(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    tracks = document.get("tracks") if isinstance(document.get("tracks"), list) else []
    rows = [
        dict(track)
        for track in tracks
        if isinstance(track, dict)
        and track.get("accepted_source_instance") is True
        and isinstance(track.get("frame_observations"), list)
        and track.get("frame_observations")
    ]
    return sorted(rows, key=lambda row: (cue_number(str(row.get("cue_id") or "")), str(row.get("cue_id") or "")))


def proven_merge_groups(document: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
    """Return only source-tracked groups that deterministically prove one instance."""
    grouped_by_token: Dict[str, List[Dict[str, Any]]] = {}
    for track in accepted_tracks(document):
        token = visual.normalize_token(track.get("text"))
        if token:
            grouped_by_token.setdefault(token, []).append(track)

    merged: List[List[Dict[str, Any]]] = []
    for token, token_tracks in sorted(grouped_by_token.items()):
        ordered = sorted(token_tracks, key=lambda row: (*visual.track_bounds(row), cue_number(str(row.get("cue_id") or ""))))
        current: List[Dict[str, Any]] = []
        for track in ordered:
            if not current:
                current = [track]
                continue
            if visual.same_visual_instance(current[-1], track):
                current.append(track)
            else:
                if len(current) > 1:
                    merged.append(current)
                current = [track]
        if len(current) > 1:
            merged.append(current)

    return sorted(
        merged,
        key=lambda group: min(cue_number(str(row.get("cue_id") or "")) for row in group),
    )


def allocate_lanes(instances: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    lane_ends: List[int] = []
    allocated: List[Dict[str, Any]] = []
    for source in sorted(
        instances,
        key=lambda row: (
            int(row["target_range"][0]),
            int(row["target_range"][1]),
            int(row["cue_index"]),
            str(row["instance_id"]),
        ),
    ):
        row = dict(source)
        start, end = [int(value) for value in row["target_range"]]
        lane = None
        for index, lane_end in enumerate(lane_ends):
            if lane_end <= start:
                lane = index + 1
                lane_ends[index] = end
                break
        if lane is None:
            lane_ends.append(end)
            lane = len(lane_ends)
        row["lane"] = lane
        row["target_track"] = CAPTION_TRACK_BASE + lane - 1
        allocated.append(row)

    overlaps: List[Dict[str, Any]] = []
    for lane in range(1, len(lane_ends) + 1):
        rows = sorted(
            [row for row in allocated if int(row["lane"]) == lane],
            key=lambda row: (int(row["target_range"][0]), int(row["target_range"][1])),
        )
        for left, right in zip(rows, rows[1:]):
            if int(left["target_range"][1]) > int(right["target_range"][0]):
                overlaps.append({"lane": lane, "left": left["instance_id"], "right": right["instance_id"]})

    usage = {str(lane): sum(1 for row in allocated if int(row["lane"]) == lane) for lane in range(1, len(lane_ends) + 1)}
    return {
        "instances": allocated,
        "lane_count": len(lane_ends),
        "lane_usage": usage,
        "same_lane_overlaps": overlaps,
        "ok": not overlaps,
    }


def ranges_overlap(left: Sequence[int], right: Sequence[int]) -> bool:
    return int(left[0]) < int(right[1]) and int(right[0]) < int(left[1])


def assign_carrier_placements(instances: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Keep visual and physical timeline ranges identical.

    Live Resolve 21 evidence shows that ``AppendToTimeline`` treats
    ``endFrame`` as an exclusive source endpoint for the resulting timeline
    duration: ``endFrame - startFrame`` timeline frames are created.  The
    previous rollout passed ``duration - 1`` and therefore shortened 114 of
    115 carriers by one frame.  V6 keeps every carrier range equal to its
    accepted half-open visual lifecycle and adds one source-only endpoint
    frame when building each clipInfo.  No extra timeline tail is created.
    """
    rows: List[Dict[str, Any]] = []
    for source in instances:
        row = dict(source)
        row["carrier_range"] = [int(value) for value in row["target_range"]]
        row["carrier_track"] = int(row["target_track"])
        row["carrier_padding"] = None
        row["append_source_end_padding_frames"] = APPEND_SOURCE_END_PADDING_FRAMES
        rows.append(row)

    one_frame_ids = [
        str(row["instance_id"])
        for row in rows
        if int(row["target_range"][1]) - int(row["target_range"][0]) == 1
    ]
    if one_frame_ids != list(EXPECTED_ONE_FRAME_CARRIER_IDS):
        raise ValueError(f"one_frame_instances:{one_frame_ids}")

    overlaps: List[Dict[str, Any]] = []
    for track in range(CAPTION_TRACK_BASE, CAPTION_TRACK_BASE + EXPECTED_LANE_COUNT):
        track_rows = sorted(
            [row for row in rows if int(row["carrier_track"]) == track],
            key=lambda row: (int(row["carrier_range"][0]), int(row["carrier_range"][1]), str(row["instance_id"])),
        )
        for left, right in zip(track_rows, track_rows[1:]):
            if ranges_overlap(left["carrier_range"], right["carrier_range"]):
                overlaps.append({
                    "track": track,
                    "left": left["instance_id"],
                    "left_range": left["carrier_range"],
                    "right": right["instance_id"],
                    "right_range": right["carrier_range"],
                })
    usage = {
        str(track): sum(1 for row in rows if int(row["carrier_track"]) == track)
        for track in range(CAPTION_TRACK_BASE, CAPTION_TRACK_BASE + EXPECTED_LANE_COUNT)
    }
    return {
        "instances": rows,
        "overrides": [],
        "one_frame_instance_ids": one_frame_ids,
        "append_source_end_padding_frames": APPEND_SOURCE_END_PADDING_FRAMES,
        "carrier_track_usage": usage,
        "carrier_overlaps": overlaps,
        "ok": bool(not overlaps),
    }

def base_item_collision_rows(
    instance: Mapping[str, Any],
    base_inventory: Sequence[Mapping[str, Any]],
    *,
    track: Optional[int] = None,
) -> List[Dict[str, Any]]:
    carrier_track = int(track if track is not None else instance.get("carrier_track", instance["target_track"]))
    carrier_range = [int(value) for value in instance.get("carrier_range", instance["target_range"])]
    rows: List[Dict[str, Any]] = []
    for item in base_inventory:
        item_track = int(item.get("track_index") or 0)
        item_range = [int(item.get("start") or 0), int(item.get("end") or 0)]
        if item_track != carrier_track or item_range[1] <= item_range[0]:
            continue
        if ranges_overlap(carrier_range, item_range):
            rows.append({
                "name": str(item.get("name") or ""),
                "media_pool_item_name": item.get("media_pool_item_name"),
                "track_index": item_track,
                "range": item_range,
            })
    return rows


def carrier_collision_rows(
    instance: Mapping[str, Any],
    instances: Sequence[Mapping[str, Any]],
    *,
    track: Optional[int] = None,
) -> List[Dict[str, Any]]:
    instance_id = str(instance["instance_id"])
    carrier_track = int(track if track is not None else instance.get("carrier_track", instance["target_track"]))
    carrier_range = [int(value) for value in instance.get("carrier_range", instance["target_range"])]
    rows: List[Dict[str, Any]] = []
    for other in instances:
        if str(other["instance_id"]) == instance_id:
            continue
        other_track = int(other.get("carrier_track", other["target_track"]))
        other_range = [int(value) for value in other.get("carrier_range", other["target_range"])]
        if other_track == carrier_track and ranges_overlap(carrier_range, other_range):
            rows.append({
                "instance_id": str(other["instance_id"]),
                "track": other_track,
                "range": other_range,
            })
    return rows


def resolve_base_carrier_collisions(
    instances: Sequence[Dict[str, Any]],
    base_inventory: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Relocate physical carriers around preserved non-caption timeline items.

    The visual lane and screen-space placement remain unchanged.  Only the
    media-backed physical carrier track may move, and only when a preserved
    base item occupies the requested carrier range.
    """
    rows: List[Dict[str, Any]] = []
    for source in instances:
        row = dict(source)
        row["carrier_range"] = [int(value) for value in source.get("carrier_range", source["target_range"])]
        row["carrier_track"] = int(source.get("carrier_track", source["target_track"]))
        rows.append(row)

    relocations: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    ordered = sorted(
        rows,
        key=lambda row: (
            int(row["carrier_range"][0]),
            int(row["carrier_range"][1]),
            int(row["cue_index"]),
            str(row["instance_id"]),
        ),
    )
    for row in ordered:
        collisions = base_item_collision_rows(row, base_inventory)
        if not collisions:
            continue
        original_track = int(row["carrier_track"])
        selected_track = None
        for candidate_track in range(CAPTION_TRACK_BASE, CAPTION_TRACK_BASE + EXPECTED_LANE_COUNT):
            if candidate_track == original_track:
                continue
            if base_item_collision_rows(row, base_inventory, track=candidate_track):
                continue
            if carrier_collision_rows(row, rows, track=candidate_track):
                continue
            selected_track = candidate_track
            break
        if selected_track is None:
            unresolved.append({
                "instance_id": str(row["instance_id"]),
                "carrier_range": list(row["carrier_range"]),
                "carrier_track": original_track,
                "base_collisions": collisions,
            })
            continue
        row["carrier_track"] = selected_track
        row["base_collision_relocation"] = {
            "mode": "preserve_base_item_relocate_physical_carrier",
            "original_track": original_track,
            "resolved_track": selected_track,
            "carrier_range": list(row["carrier_range"]),
            "base_collisions": collisions,
        }
        relocations.append({
            "instance_id": str(row["instance_id"]),
            "visible_track": int(row["target_track"]),
            "visible_range": [int(value) for value in row["target_range"]],
            "carrier_range": list(row["carrier_range"]),
            "original_carrier_track": original_track,
            "resolved_carrier_track": selected_track,
            "base_collisions": collisions,
        })

    remaining_base_collisions: List[Dict[str, Any]] = []
    for row in rows:
        collisions = base_item_collision_rows(row, base_inventory)
        if collisions:
            remaining_base_collisions.append({
                "instance_id": str(row["instance_id"]),
                "carrier_track": int(row["carrier_track"]),
                "carrier_range": list(row["carrier_range"]),
                "base_collisions": collisions,
            })

    carrier_overlaps: List[Dict[str, Any]] = []
    for track in range(CAPTION_TRACK_BASE, CAPTION_TRACK_BASE + EXPECTED_LANE_COUNT):
        track_rows = sorted(
            [row for row in rows if int(row["carrier_track"]) == track],
            key=lambda row: (int(row["carrier_range"][0]), int(row["carrier_range"][1]), str(row["instance_id"])),
        )
        for left, right in zip(track_rows, track_rows[1:]):
            if ranges_overlap(left["carrier_range"], right["carrier_range"]):
                carrier_overlaps.append({
                    "track": track,
                    "left": str(left["instance_id"]),
                    "left_range": list(left["carrier_range"]),
                    "right": str(right["instance_id"]),
                    "right_range": list(right["carrier_range"]),
                })

    usage = {
        str(track): sum(1 for row in rows if int(row["carrier_track"]) == track)
        for track in range(CAPTION_TRACK_BASE, CAPTION_TRACK_BASE + EXPECTED_LANE_COUNT)
    }
    relocation_ids = [str(row["instance_id"]) for row in relocations]
    return {
        "instances": rows,
        "relocations": relocations,
        "relocation_ids": relocation_ids,
        "relocation_count": len(relocations),
        "unresolved": unresolved,
        "remaining_base_collisions": remaining_base_collisions,
        "carrier_overlaps": carrier_overlaps,
        "carrier_track_usage": usage,
        "ok": bool(
            not unresolved
            and not remaining_base_collisions
            and not carrier_overlaps
            and relocation_ids == list(EXPECTED_BASE_COLLISION_RELOCATION_IDS)
            and usage == EXPECTED_RUNTIME_CARRIER_TRACK_USAGE
        ),
    }


def audit_append_payloads(
    instances: Sequence[Dict[str, Any]],
    base_inventory: Sequence[Mapping[str, Any]],
    carrier_source: Mapping[str, Any],
) -> Dict[str, Any]:
    specs = append_specs(instances)
    attempts = carrier_source.get("attempts") if isinstance(carrier_source.get("attempts"), list) else []
    durations = [int(row.get("duration") or 0) for row in attempts if isinstance(row, dict)]
    source_duration = max(durations, default=0)
    source_start = int(carrier_source.get("source_start") or 0)
    media_pool_item_available = carrier_source.get("media_pool_item") is not None
    rows: List[Dict[str, Any]] = []
    issues: List[str] = []
    placements: Dict[Tuple[int, int, int], List[str]] = {}

    for spec in specs:
        carrier_range = [int(value) for value in spec["carrier_range"]]
        duration = carrier_range[1] - carrier_range[0]
        track = int(spec["carrier_track"])
        source_end = source_start + duration
        append_source_span = source_end - source_start + 1
        row_issues: List[str] = []
        if duration < 1:
            row_issues.append("carrier_duration")
        if append_source_span < MIN_APPEND_SOURCE_DURATION:
            row_issues.append("append_source_span")
        if track < CAPTION_TRACK_BASE or track >= CAPTION_TRACK_BASE + EXPECTED_LANE_COUNT:
            row_issues.append("carrier_track")
        if source_duration <= 0 or source_end >= source_start + source_duration:
            row_issues.append("source_range")
        base_collisions = base_item_collision_rows(
            {
                "target_track": track,
                "target_range": carrier_range,
                "carrier_track": track,
                "carrier_range": carrier_range,
            },
            base_inventory,
        )
        if base_collisions:
            row_issues.append("base_collision")
        placement_key = (track, carrier_range[0], carrier_range[1])
        placements.setdefault(placement_key, []).append(str(spec["cue_id"]))
        rows.append({
            "cue_id": str(spec["cue_id"]),
            "carrier_track": track,
            "carrier_range": carrier_range,
            "duration": duration,
            "append_source_span": append_source_span,
            "append_source_end_padding_frames": APPEND_SOURCE_END_PADDING_FRAMES,
            "clip_info": {
                "startFrame": source_start,
                "endFrame": source_end,
                "recordFrame": carrier_range[0],
                "trackIndex": track,
                "mediaType": 1,
            },
            "base_collisions": base_collisions,
            "issues": row_issues,
            "ok": not row_issues,
        })
        issues.extend(f"{spec['cue_id']}:{issue}" for issue in row_issues)

    duplicate_placements = [
        {"track": key[0], "range": [key[1], key[2]], "cue_ids": cue_ids}
        for key, cue_ids in placements.items()
        if len(cue_ids) > 1
    ]
    if duplicate_placements:
        issues.append("duplicate_placements")
    carrier_overlaps: List[Dict[str, Any]] = []
    for track in range(CAPTION_TRACK_BASE, CAPTION_TRACK_BASE + EXPECTED_LANE_COUNT):
        track_rows = sorted(
            [row for row in rows if int(row["carrier_track"]) == track],
            key=lambda row: (int(row["carrier_range"][0]), int(row["carrier_range"][1]), str(row["cue_id"])),
        )
        for left, right in zip(track_rows, track_rows[1:]):
            if ranges_overlap(left["carrier_range"], right["carrier_range"]):
                carrier_overlaps.append({
                    "track": track,
                    "left": left["cue_id"],
                    "left_range": left["carrier_range"],
                    "right": right["cue_id"],
                    "right_range": right["carrier_range"],
                })
    if carrier_overlaps:
        issues.append("carrier_overlaps")
    if not media_pool_item_available:
        issues.append("media_pool_item")
    if len(rows) != EXPECTED_INSTANCE_COUNT:
        issues.append(f"instance_count:{len(rows)}")

    return {
        "expected_count": EXPECTED_INSTANCE_COUNT,
        "payload_count": len(rows),
        "media_pool_item_available": media_pool_item_available,
        "source_start": source_start,
        "source_duration": source_duration,
        "append_source_end_padding_frames": APPEND_SOURCE_END_PADDING_FRAMES,
        "rows": rows,
        "duplicate_placements": duplicate_placements,
        "carrier_overlaps": carrier_overlaps,
        "issue_count": len(issues),
        "issues": issues,
        "ok": bool(
            len(rows) == EXPECTED_INSTANCE_COUNT
            and media_pool_item_available
            and source_duration > 0
            and all(row["ok"] for row in rows)
            and not duplicate_placements
            and not carrier_overlaps
        ),
    }


def compile_rollout_plan(
    lifecycle_document: Dict[str, Any],
    word_tracks_document: Dict[str, Any],
    controller_document: Dict[str, Any],
    animation_document: Dict[str, Any],
) -> Dict[str, Any]:
    layers = lifecycle_document.get("layers") if isinstance(lifecycle_document.get("layers"), list) else []
    if lifecycle_document.get("ok") is not True or len(layers) != EXPECTED_SOURCE_CAPTION_COUNT:
        raise ValueError("lifecycle_authority")
    by_cue = {str(row.get("cue_id") or ""): dict(row) for row in layers if isinstance(row, dict)}
    if len(by_cue) != EXPECTED_SOURCE_CAPTION_COUNT:
        raise ValueError("lifecycle_cues")

    controller = controller_item_map(controller_document)
    if len(controller) != EXPECTED_SOURCE_CAPTION_COUNT or set(controller) != set(by_cue):
        raise ValueError("controller_coverage")
    animations = animation_map(animation_document)
    if len(animations) != EXPECTED_ANIMATED_COUNT:
        raise ValueError("animation_count")

    merge_groups = proven_merge_groups(word_tracks_document)
    merge_aliases = [[str(row.get("cue_id") or "") for row in group] for group in merge_groups]
    # The accepted evidence proves exactly this one merge. Any additional merge
    # requires a separate visual approval boundary rather than silent rollout.
    if merge_aliases != [["sub_051", "sub_054"]]:
        raise ValueError(f"merge_groups:{merge_aliases}")

    alias_to_group: Dict[str, List[Dict[str, Any]]] = {}
    for group in merge_groups:
        for track in group:
            alias_to_group[str(track.get("cue_id") or "")] = group

    instances: List[Dict[str, Any]] = []
    represented: List[str] = []
    consumed: set[str] = set()
    for cue_id in sorted(by_cue, key=cue_number):
        if cue_id in consumed:
            continue
        layer = by_cue[cue_id]
        group = alias_to_group.get(cue_id)
        if group:
            aliases = sorted((str(row.get("cue_id") or "") for row in group), key=cue_number)
            if cue_id != aliases[0]:
                consumed.add(cue_id)
                continue
            if any(alias in animations for alias in aliases):
                raise ValueError(f"merged_animation:{aliases}")
            they_plan = visual.select_they_visual_instance(word_tracks_document, visual.COME_SOURCE["target_range"])
            if aliases != they_plan.get("source_cue_ids") or not they_plan.get("ok"):
                raise ValueError("merged_they_plan")
            style_source = str(they_plan["style_source_cue_id"])
            source_row = controller[style_source]
            latest_text = str(by_cue[aliases[-1]].get("text") or "")
            instances.append({
                "instance_id": "visual_instance_sub_051_sub_054",
                "cue_index": min(cue_number(alias) for alias in aliases),
                "source_cue_ids": aliases,
                "style_source_cue_id": style_source,
                "source_name": str(by_cue[style_source].get("name") or ""),
                "source_range": [int(source_row["start_frame"]), int(source_row["end_frame"])],
                "target_name": visual.THEY_TARGET_NAME,
                "target_range": [int(value) for value in they_plan["visual_window"]],
                "text": latest_text,
                "timing_authority": "visual_instance_merge",
                "visual_primary": True,
                "animation_selected": False,
                "animation": None,
                "correction_profile": "merged_they_v3",
                "merge_evidence": {
                    "selection_basis": they_plan.get("selection_basis"),
                    "source_cue_ids": aliases,
                    "style_source_cue_id": style_source,
                    "visual_window": list(they_plan["visual_window"]),
                },
            })
            represented.extend(aliases)
            consumed.update(aliases)
            continue

        source_row = controller[cue_id]
        selected_animation = bool(layer.get("animation_selected_step_3C"))
        animation = animations.get(cue_id)
        if selected_animation != (animation is not None):
            raise ValueError(f"animation_authority:{cue_id}")
        target_range = [int(value) for value in layer.get("lifecycle_window") or []]
        source_range = [int(source_row["start_frame"]), int(source_row["end_frame"])]
        if len(target_range) != 2 or target_range[1] <= target_range[0]:
            raise ValueError(f"target_range:{cue_id}")
        if source_range[1] <= source_range[0]:
            raise ValueError(f"source_range:{cue_id}")
        if animation:
            max_frame = max(int(target["local_frame"]) for target in animation["targets"])
            if max_frame >= target_range[1] - target_range[0]:
                raise ValueError(f"animation_duration:{cue_id}")
        instances.append({
            "instance_id": cue_id,
            "cue_index": int(layer.get("cue_index") or cue_number(cue_id)),
            "source_cue_ids": [cue_id],
            "style_source_cue_id": cue_id,
            "source_name": str(layer.get("name") or ""),
            "source_range": source_range,
            "target_name": str(layer.get("name") or ""),
            "target_range": target_range,
            "text": str(layer.get("text") or ""),
            "timing_authority": str(layer.get("timing_authority") or ""),
            "visual_primary": str(layer.get("timing_authority") or "").startswith("visual_primary"),
            "animation_selected": selected_animation,
            "animation": animation,
            "correction_profile": "come_v3" if cue_id == "sub_052" else "source_comp",
            "merge_evidence": None,
        })
        represented.append(cue_id)
        consumed.add(cue_id)

    lanes = allocate_lanes(instances)
    carrier_plan = assign_carrier_placements(lanes["instances"])
    allocated = carrier_plan["instances"]
    visual_primary_layers = sum(1 for layer in layers if str(layer.get("timing_authority") or "").startswith("visual_primary"))
    transcript_fallback_layers = sum(1 for layer in layers if layer.get("timing_authority") == "transcript_fallback")
    animated = [row for row in allocated if row.get("animation_selected")]
    summary = {
        "source_layer_count": len(layers),
        "visual_instance_count": len(allocated),
        "represented_cue_count": len(represented),
        "represented_cue_ids_unique": len(set(represented)),
        "merge_group_count": len(merge_groups),
        "merged_aliases": merge_aliases,
        "animated_instance_count": len(animated),
        "visual_primary_source_layer_count": visual_primary_layers,
        "transcript_fallback_source_layer_count": transcript_fallback_layers,
        "lane_count": lanes["lane_count"],
        "lane_usage": lanes["lane_usage"],
        "same_lane_overlap_count": len(lanes["same_lane_overlaps"]),
        "one_frame_carrier_count": len(carrier_plan["one_frame_instance_ids"]),
        "one_frame_carrier_ids": list(carrier_plan["one_frame_instance_ids"]),
        "carrier_track_usage": carrier_plan["carrier_track_usage"],
        "carrier_overlap_count": len(carrier_plan["carrier_overlaps"]),
        "target_track_min": min(int(row["target_track"]) for row in allocated),
        "target_track_max": max(int(row["target_track"]) for row in allocated),
    }
    checks = {
        "source_layer_count": summary["source_layer_count"] == EXPECTED_SOURCE_CAPTION_COUNT,
        "visual_instance_count": summary["visual_instance_count"] == EXPECTED_INSTANCE_COUNT,
        "alias_coverage": summary["represented_cue_count"] == EXPECTED_ALIAS_COVERAGE and summary["represented_cue_ids_unique"] == EXPECTED_ALIAS_COVERAGE,
        "merge_group": merge_aliases == [["sub_051", "sub_054"]],
        "animated_count": summary["animated_instance_count"] == EXPECTED_ANIMATED_COUNT,
        "visual_primary_count": visual_primary_layers == 49,
        "transcript_fallback_count": transcript_fallback_layers == 67,
        "lane_count": summary["lane_count"] == EXPECTED_LANE_COUNT,
        "lane_usage": summary["lane_usage"] == {"1": 71, "2": 22, "3": 16, "4": 5, "5": 1},
        "one_frame_carriers": summary["one_frame_carrier_ids"] == list(EXPECTED_ONE_FRAME_CARRIER_IDS),
        "carrier_track_usage": summary["carrier_track_usage"] == {"3": 71, "4": 22, "5": 16, "6": 5, "7": 1},
        "carrier_overlaps": summary["carrier_overlap_count"] == 0,
        "same_lane_overlaps": summary["same_lane_overlap_count"] == 0,
        "target_tracks": summary["target_track_min"] == 3 and summary["target_track_max"] == 7,
        "names_unique": len({row["target_name"] for row in allocated}) == EXPECTED_INSTANCE_COUNT,
        "source_names": all(bool(row["source_name"]) for row in allocated),
        "target_names": all(bool(row["target_name"]) for row in allocated),
    }
    source_catalog = [
        {
            "cue_id": cue_id,
            "cue_index": int(by_cue[cue_id].get("cue_index") or cue_number(cue_id)),
            "name": str(by_cue[cue_id].get("name") or ""),
            "text": str(by_cue[cue_id].get("text") or ""),
            "source_range": [int(controller[cue_id]["start_frame"]), int(controller[cue_id]["end_frame"])],
        }
        for cue_id in sorted(by_cue, key=cue_number)
    ]
    checks["source_catalog"] = bool(
        len(source_catalog) == EXPECTED_SOURCE_CAPTION_COUNT
        and len({row["name"] for row in source_catalog}) == EXPECTED_SOURCE_CAPTION_COUNT
        and all(row["name"] and row["source_range"][1] > row["source_range"][0] for row in source_catalog)
    )
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "authority_policy": lifecycle_document.get("authority_policy"),
        "instances": allocated,
        "source_catalog": source_catalog,
        "summary": summary,
        "checks": checks,
        "same_lane_overlaps": lanes["same_lane_overlaps"],
        "carrier_overrides": carrier_plan["overrides"],
        "carrier_overlaps": carrier_plan["carrier_overlaps"],
        "ok": all(checks.values()) and carrier_plan["ok"],
    }


def capture_signature(text_tool: Any) -> Dict[str, Any]:
    if text_tool is None:
        return {"ok": False, "values": {}}
    values: Dict[str, Any] = {}
    for input_name in SIGNATURE_POINT_INPUTS:
        if base.find_input(text_tool, input_name) is None:
            continue
        point = base.normalize_point(base.read_input(text_tool, input_name, 0))
        if point is not None:
            values[input_name] = [float(point[0]), float(point[1])]
    for input_name in SIGNATURE_SCALAR_INPUTS:
        if base.find_input(text_tool, input_name) is None:
            continue
        value = base.read_input(text_tool, input_name, 0)
        try:
            values[input_name] = float(value)
        except (TypeError, ValueError):
            continue
    return {"ok": bool(values), "values": values}


def signature_matches(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
    ignored: Iterable[str] = (),
    overrides: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    ignored_set = set(ignored)
    expected_values = dict(expected)
    if overrides:
        expected_values.update(overrides)
    rows = []
    keys = sorted(key for key in expected_values if key not in ignored_set)
    for input_name in keys:
        wanted = expected_values[input_name]
        got = actual.get(input_name)
        if input_name in SIGNATURE_POINT_INPUTS:
            matched = base.point_matches(got, list(wanted), tolerance=visual.POINT_TOLERANCE)
        else:
            matched = visual.scalar_matches(got, float(wanted), tolerance=1e-4)
        rows.append({"input": input_name, "expected": base.json_safe(wanted), "actual": base.json_safe(got), "matched": matched})
    return {"rows": rows, "ok": bool(rows and all(row["matched"] for row in rows))}


def source_range_verdict(actual_range: Sequence[Any], expected_range: Sequence[Any]) -> Dict[str, Any]:
    """Accept exact protected-source bounds or Resolve's proven one- or two-frame-short end readback."""
    try:
        actual_start, actual_end = [int(value) for value in actual_range]
        expected_start, expected_end = [int(value) for value in expected_range]
    except (TypeError, ValueError):
        return {
            "policy": SOURCE_RANGE_POLICY,
            "actual_range": base.json_safe(actual_range),
            "expected_range": base.json_safe(expected_range),
            "classification": "invalid",
            "ok": False,
        }

    start_delta = actual_start - expected_start
    end_delta = actual_end - expected_end
    if start_delta == 0 and end_delta == 0:
        classification = "exact"
        ok = actual_end > actual_start
    elif start_delta == 0 and end_delta in {-1, -2}:
        classification = "resolve_end_shortened"
        ok = actual_end > actual_start
    else:
        classification = "mismatch"
        ok = False
    return {
        "policy": SOURCE_RANGE_POLICY,
        "actual_range": [actual_start, actual_end],
        "expected_range": [expected_start, expected_end],
        "start_delta": start_delta,
        "end_delta": end_delta,
        "classification": classification,
        "ok": ok,
    }


def source_snapshot(timeline: Any, plan: Dict[str, Any]) -> Dict[str, Any]:
    animation_by_cue = {
        str(row["style_source_cue_id"]): row.get("animation")
        for row in plan["instances"]
        if row.get("animation")
    }
    rows = []
    for source_row in plan.get("source_catalog") or []:
        cue_id = str(source_row["cue_id"])
        source_name = str(source_row["name"])
        track, item = base.find_named_item(timeline, source_name)
        if item is None:
            rows.append({"cue_id": cue_id, "name": source_name, "found": False, "ok": False})
            continue
        summary = base.item_summary(int(track or 0), item)
        comp = base.get_comp(item)
        tool = base.get_text_tool(comp)
        text = base.text_readback(tool) if tool is not None else ""
        signature = capture_signature(tool)
        animation = animation_by_cue.get(cue_id)
        animation_rows = []
        if animation:
            for target in animation["targets"]:
                input_name = str(target["input"])
                frame = int(target["local_frame"])
                expected = target["expected"]
                actual = base.read_input(tool, input_name, frame) if tool is not None else None
                animation_rows.append({
                    "input": input_name,
                    "local_frame": frame,
                    "expected": base.json_safe(expected),
                    "actual": base.json_safe(actual),
                    "matched": visual.value_matches(input_name, actual, expected),
                })
        actual_range = [summary["start"], summary["end"]]
        expected_range = list(source_row["source_range"])
        range_verdict = source_range_verdict(actual_range, expected_range)
        row_ok = bool(
            range_verdict.get("ok")
            and summary.get("fusion_comp_count") == 1
            and signature.get("ok")
            and text
            and (not animation_rows or all(row["matched"] for row in animation_rows))
        )
        rows.append({
            "cue_id": cue_id,
            "name": source_name,
            "found": True,
            "expected_range": expected_range,
            "actual_range": actual_range,
            "range_verdict": range_verdict,
            "summary": summary,
            "text": text,
            "signature": signature,
            "animation_targets": animation_rows,
            "ok": row_ok,
        })
    adjustments = [
        str(row["cue_id"])
        for row in rows
        if (row.get("range_verdict") or {}).get("classification") == "resolve_end_shortened"
    ]
    invalid_ranges = [
        str(row.get("cue_id") or "")
        for row in rows
        if row.get("found") and not (row.get("range_verdict") or {}).get("ok")
    ]
    return {
        "range_policy": SOURCE_RANGE_POLICY,
        "rows": rows,
        "caption_count": len(rows),
        "ok_count": sum(1 for row in rows if row.get("ok")),
        "range_adjustment_count": len(adjustments),
        "range_adjustment_cue_ids": adjustments,
        "invalid_range_cue_ids": invalid_ranges,
        "ok": len(rows) == EXPECTED_SOURCE_CAPTION_COUNT and all(row.get("ok") for row in rows),
    }


def stable_source_snapshot(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for row in snapshot.get("rows") or []:
        summary = row.get("summary") or {}
        rows.append({
            "cue_id": row.get("cue_id"),
            "name": row.get("name"),
            "found": row.get("found"),
            "unique_id": summary.get("unique_id"),
            "track_index": summary.get("track_index"),
            "start": summary.get("start"),
            "end": summary.get("end"),
            "fusion_comp_count": summary.get("fusion_comp_count"),
            "text": row.get("text"),
            "signature": (row.get("signature") or {}).get("values"),
            "animation_targets": [
                {
                    "input": target.get("input"),
                    "local_frame": target.get("local_frame"),
                    "actual": target.get("actual"),
                }
                for target in row.get("animation_targets") or []
            ],
        })
    return rows


def non_caption_inventory(timeline: Any) -> List[Dict[str, Any]]:
    rows = []
    for track, item in base.all_video_items(timeline):
        if base.item_name(item).startswith(base.CAPTION_PREFIX):
            continue
        summary = base.item_summary(track, item)
        rows.append({
            "name": summary["name"],
            "unique_id": summary["unique_id"],
            "track_index": summary["track_index"],
            "start": summary["start"],
            "end": summary["end"],
            "duration": summary["duration"],
            "media_pool_item_name": summary["media_pool_item_name"],
        })
    return sorted(rows, key=lambda row: (row["track_index"], row["start"], row["end"], row["name"]))


def stable_non_caption_inventory(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    stable = [
        {field: row.get(field) for field in BASE_INVENTORY_STABLE_FIELDS}
        for row in rows
    ]
    return sorted(
        stable,
        key=lambda row: (
            int(row["track_index"] or 0),
            int(row["start"] or 0),
            int(row["end"] or 0),
            str(row["name"] or ""),
            str(row["media_pool_item_name"] or ""),
        ),
    )


def compare_non_caption_inventory(
    source_rows: Sequence[Mapping[str, Any]],
    target_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    source_stable = stable_non_caption_inventory(source_rows)
    target_stable = stable_non_caption_inventory(target_rows)
    first_mismatch = None
    for index in range(max(len(source_stable), len(target_stable))):
        source_row = source_stable[index] if index < len(source_stable) else None
        target_row = target_stable[index] if index < len(target_stable) else None
        if source_row != target_row:
            first_mismatch = {
                "index": index,
                "source": source_row,
                "target": target_row,
            }
            break
    return {
        "comparison_fields": list(BASE_INVENTORY_STABLE_FIELDS),
        "source_count": len(source_stable),
        "target_count": len(target_stable),
        "first_mismatch": first_mismatch,
        "ok": source_stable == target_stable,
    }


def append_specs(instance_rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "cue_id": str(row["instance_id"]),
            "name": str(row["target_name"]),
            "text": str(row["text"]),
            "target_range": [int(value) for value in row["target_range"]],
            "target_track": int(row["target_track"]),
            "carrier_range": [int(value) for value in row.get("carrier_range", row["target_range"])],
            "carrier_track": int(row.get("carrier_track", row["target_track"])),
            "carrier_padding": row.get("carrier_padding"),
        }
        for row in instance_rows
    ]


def batch_rows(rows: Sequence[Dict[str, Any]], size: int = APPEND_BATCH_SIZE) -> List[List[Dict[str, Any]]]:
    ordered = sorted(rows, key=lambda row: (int(row.get("carrier_track", row["target_track"])), int(row.get("carrier_range", row["target_range"])[0]), str(row["cue_id"])))
    batches = []
    for track in sorted({int(row.get("carrier_track", row["target_track"])) for row in ordered}):
        track_rows = [row for row in ordered if int(row.get("carrier_track", row["target_track"])) == track]
        for index in range(0, len(track_rows), size):
            batches.append(track_rows[index:index + size])
    return batches


def exact_carrier_placement_ok(summary: Mapping[str, Any], spec: Mapping[str, Any]) -> bool:
    """Require the live item to preserve the complete half-open carrier range."""
    start, end = [int(value) for value in spec["target_range"]]
    expected_duration = end - start
    return bool(
        int(summary.get("track_index") or 0) == int(spec["target_track"])
        and int(summary.get("start") or -1) == start
        and int(summary.get("end") or -1) == end
        and int(summary.get("duration") or -1) == expected_duration
    )


def append_batch_by_placement(
    media_pool: Any,
    timeline: Any,
    carrier_source: Dict[str, Any],
    specs: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    before_ids = {base.item_unique_id(item) for _, item in base.all_video_items(timeline) if base.item_unique_id(item)}
    clip_infos = []
    for spec in specs:
        start, end = [int(value) for value in spec.get("carrier_range", spec["target_range"])]
        duration = end - start
        if duration < 1:
            raise ValueError(f"append_duration:{spec['cue_id']}:{duration}")
        clip_infos.append({
            "mediaPoolItem": carrier_source["media_pool_item"],
            "startFrame": int(carrier_source["source_start"]),
            "endFrame": int(carrier_source["source_start"]) + duration,
            "mediaType": 1,
            "trackIndex": int(spec.get("carrier_track", spec["target_track"])),
            "recordFrame": start,
        })
    returned, call = base.direct_call(media_pool, "AppendToTimeline", clip_infos)
    time.sleep(0.25)
    returned_items = list(returned) if isinstance(returned, (list, tuple)) else []
    detected_items = [
        item
        for _, item in base.all_video_items(timeline)
        if base.item_unique_id(item) and base.item_unique_id(item) not in before_ids
    ]
    candidates: List[Any] = []
    seen = set()
    for item in [*returned_items, *detected_items]:
        key = base.item_unique_id(item) or repr(item)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(item)

    candidate_rows = []
    for item in candidates:
        track = int(base.item_track_index(timeline, item) or 0)
        candidate_rows.append({"item": item, "summary": base.item_summary(track, item), "key": base.item_unique_id(item) or repr(item)})

    assigned: List[Tuple[Dict[str, Any], Any]] = []
    rows = []
    used = set()
    for spec in specs:
        carrier_placement = {
            "target_track": int(spec.get("carrier_track", spec["target_track"])),
            "target_range": [int(value) for value in spec.get("carrier_range", spec["target_range"])],
        }
        matches = [row for row in candidate_rows if row["key"] not in used and exact_carrier_placement_ok(row["summary"], carrier_placement)]
        if len(matches) != 1:
            rows.append({
                "cue_id": spec["cue_id"],
                "expected_track": carrier_placement["target_track"],
                "expected_range": carrier_placement["target_range"],
                "visible_track": spec["target_track"],
                "visible_range": spec["target_range"],
                "match_count": len(matches),
                "ok": False,
            })
            continue
        selected = matches[0]
        used.add(selected["key"])
        name_write = base.set_item_name(selected["item"], spec["name"])
        time.sleep(0.05)
        track, reacquired = base.find_named_item(timeline, spec["name"])
        item = reacquired if reacquired is not None else selected["item"]
        summary = base.item_summary(int(track or base.item_track_index(timeline, item) or 0), item)
        ok = bool(name_write.get("ok") and exact_carrier_placement_ok(summary, carrier_placement))
        rows.append({
            "cue_id": spec["cue_id"],
            "name": spec["name"],
            "name_write": name_write,
            "summary": summary,
            "ok": ok,
        })
        if ok:
            assigned.append((dict(spec), item))

    return {
        "call": call,
        "requested_count": len(specs),
        "returned_count": len(returned_items),
        "detected_count": len(detected_items),
        "candidate_count": len(candidates),
        "assigned_count": len(assigned),
        "clip_infos": [{key: (str(value) if key == "mediaPoolItem" else value) for key, value in info.items()} for info in clip_infos],
        "candidates": [{"key": row["key"], "summary": row["summary"]} for row in candidate_rows],
        "rows": rows,
        "assigned": assigned,
        "ok": len(assigned) == len(specs) and all(row.get("ok") for row in rows),
    }


def apply_instance(item: Any, instance: Dict[str, Any], special_plans: Dict[str, Any]) -> Dict[str, Any]:
    profile = str(instance["correction_profile"])
    if profile == "come_v3":
        text_tool = base.get_text_tool(base.get_comp(item))
        text_write = visual.set_static(text_tool, "StyledText", instance["text"]) if text_tool is not None else {"ok": False}
        correction = visual.apply_come_correction(item, special_plans["come"])
        return {"profile": profile, "text": text_write, "correction": correction, "ok": bool(text_write.get("ok") and correction.get("ok"))}
    if profile == "merged_they_v3":
        correction = visual.apply_they_correction(item, special_plans["they"])
        return {"profile": profile, "correction": correction, "ok": correction.get("ok") is True}
    comp = base.get_comp(item)
    text_tool = base.get_text_tool(comp)
    if comp is None or text_tool is None:
        return {"profile": profile, "ok": False, "error": "comp_or_text"}
    duration = int(instance["target_range"][1]) - int(instance["target_range"][0])
    comp_range = visual.extend_comp_range(comp, text_tool, duration - 1)
    text_write = visual.set_static(text_tool, "StyledText", instance["text"])
    return {"profile": profile, "comp_range": comp_range, "text": text_write, "ok": bool(comp_range.get("ok") and text_write.get("ok"))}


def read_animation_targets(text_tool: Any, animation: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not animation:
        return {"selected": False, "rows": [], "ok": True}
    rows = []
    for target in animation["targets"]:
        input_name = str(target["input"])
        frame = int(target["local_frame"])
        expected = target["expected"]
        actual = base.read_input(text_tool, input_name, frame) if text_tool is not None else None
        rows.append({
            "input": input_name,
            "local_frame": frame,
            "expected": base.json_safe(expected),
            "actual": base.json_safe(actual),
            "matched": visual.value_matches(input_name, actual, expected),
        })
    return {"selected": True, "type": animation.get("animation_type"), "rows": rows, "ok": bool(rows and all(row["matched"] for row in rows))}


def expected_signature_for_instance(instance: Dict[str, Any], source_values: Dict[str, Any]) -> Dict[str, Any]:
    expected = dict(source_values)
    if instance["correction_profile"] == "come_v3":
        expected.update(visual.COME_SOURCE_FRAME_STYLE)
    return expected


def persistent_instance_readback(
    timeline: Any,
    instance: Dict[str, Any],
    source_signature: Dict[str, Any],
    application: Dict[str, Any],
    special_plans: Dict[str, Any],
) -> Dict[str, Any]:
    track, item = base.find_named_item(timeline, instance["target_name"])
    if item is None:
        return {"instance_id": instance["instance_id"], "found": False, "ok": False}
    summary = base.item_summary(int(track or 0), item)
    comp = base.get_comp(item)
    text_tool = base.get_text_tool(comp)
    actual_text = base.text_readback(text_tool) if text_tool is not None else ""
    signature = capture_signature(text_tool)
    ignored = []
    if instance["correction_profile"] == "merged_they_v3":
        ignored = ["Center", "Opacity1", "Opacity2", "Opacity3"]
    expected_signature = expected_signature_for_instance(instance, source_signature)
    signature_result = signature_matches(signature.get("values") or {}, expected_signature, ignored=ignored)
    animation = read_animation_targets(text_tool, instance.get("animation"))
    duration = int(instance["target_range"][1]) - int(instance["target_range"][0])
    global_out = base.read_input(text_tool, "GlobalOut", 0) if text_tool is not None else None
    carrier_padding = instance.get("carrier_padding") if isinstance(instance.get("carrier_padding"), dict) else None
    global_out_value = base.as_int(global_out, -1)
    comp_range_ok = (
        global_out_value == duration - 1
        if carrier_padding
        else global_out_value >= duration - 1
    )
    carrier_placement = {
        "target_track": int(instance.get("carrier_track", instance["target_track"])),
        "target_range": [int(value) for value in instance.get("carrier_range", instance["target_range"])],
    }
    placement = exact_carrier_placement_ok(summary, carrier_placement)
    expected_timeline_duration = int(carrier_placement["target_range"][1]) - int(carrier_placement["target_range"][0])
    actual_timeline_duration = int(summary.get("duration") or -1)
    exact_duration_ok = actual_timeline_duration == expected_timeline_duration
    transparent_tail_ok = bool(
        not carrier_padding
        or (
            carrier_padding.get("mode") == "minimum_two_frame_carrier_transparent_tail"
            and global_out_value == int(carrier_padding.get("expected_text_global_out", -1))
            and int(instance["carrier_range"][1]) - int(instance["carrier_range"][0]) == MIN_APPEND_SOURCE_DURATION
            and int(instance["target_range"][1]) - int(instance["target_range"][0]) == 1
        )
    )
    special: Dict[str, Any] = {"ok": True}
    if instance["correction_profile"] == "come_v3":
        come_readback = visual.persistent_visual_readback(
            item,
            instance["text"],
            special_plans["come"]["center_keys"],
            special_plans["come"]["opacity_keys"],
            application["correction"]["opacity"]["base_values"],
        )
        special = {"come": come_readback, "ok": come_readback.get("ok") is True}
    elif instance["correction_profile"] == "merged_they_v3":
        they_readback = visual.persistent_visual_readback(
            item,
            instance["text"],
            special_plans["they"]["position_keys"],
            special_plans["they"]["opacity_keys"],
            application["correction"]["opacity"]["base_values"],
        )
        special = {
            "they": they_readback,
            "stabilization": special_plans["they"].get("stabilization"),
            "ok": bool(they_readback.get("ok") and (special_plans["they"].get("stabilization") or {}).get("ok")),
        }
    ok = bool(
        placement
        and summary.get("fusion_comp_count") == 1
        and actual_text == instance["text"]
        and comp_range_ok
        and transparent_tail_ok
        and signature_result.get("ok")
        and animation.get("ok")
        and special.get("ok")
    )
    return {
        "instance_id": instance["instance_id"],
        "target_name": instance["target_name"],
        "source_cue_ids": instance["source_cue_ids"],
        "found": True,
        "summary": summary,
        "placement_ok": placement,
        "expected_timeline_duration": expected_timeline_duration,
        "actual_timeline_duration": actual_timeline_duration,
        "exact_duration_ok": exact_duration_ok,
        "visible_track": instance["target_track"],
        "visible_range": instance["target_range"],
        "carrier_track": instance.get("carrier_track", instance["target_track"]),
        "carrier_range": instance.get("carrier_range", instance["target_range"]),
        "carrier_padding": carrier_padding,
        "transparent_tail_ok": transparent_tail_ok,
        "expected_text": instance["text"],
        "actual_text": actual_text,
        "text_ok": actual_text == instance["text"],
        "global_out": base.json_safe(global_out),
        "comp_range_ok": comp_range_ok,
        "signature": signature,
        "signature_comparison": signature_result,
        "animation": animation,
        "special": special,
        "ok": ok,
    }


def timeline_overlap_audit(timeline: Any, instances: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    overlaps = []
    for track in range(CAPTION_TRACK_BASE, CAPTION_TRACK_BASE + EXPECTED_LANE_COUNT):
        names = {row["target_name"] for row in instances if int(row.get("carrier_track", row["target_track"])) == track}
        items = []
        for item in base.track_items(timeline, "video", track):
            if base.item_name(item) in names:
                items.append(base.item_summary(track, item))
        items.sort(key=lambda row: (int(row["start"]), int(row["end"]), str(row["name"])))
        for left, right in zip(items, items[1:]):
            if int(left["end"]) > int(right["start"]):
                overlaps.append({"track": track, "left": left, "right": right})
        rows.append({"track": track, "expected_count": len(names), "actual_count": len(items), "items": items})
    return {
        "tracks": rows,
        "same_track_overlaps": overlaps,
        "target_count": sum(row["actual_count"] for row in rows),
        "ok": bool(sum(row["actual_count"] for row in rows) == EXPECTED_INSTANCE_COUNT and not overlaps and all(row["expected_count"] == row["actual_count"] for row in rows)),
    }


def cleanup_target(
    resolve: Any,
    target_name: str,
    original_name: str,
    original_page: str,
    root: Path,
    accepted_hash: str,
) -> Dict[str, Any]:
    return media.cleanup_probe(resolve, target_name, original_name, original_page, root, accepted_hash)


def run(resolve: Any, context: Dict[str, Any]) -> Dict[str, Any]:
    root = base.repository_root()
    command = context.get("command") if isinstance(context, dict) else None
    if not isinstance(command, dict):
        raise ValueError("command")
    run_id = str(context.get("run_id") or command.get("run_id") or "")
    if not run_id:
        raise ValueError("run_id")
    if command.get("task_id") != TASK_ID or command.get("mode") != MODE:
        raise ValueError("command_identity")
    report_dir = base.relative_path(root, command.get("artifacts_dir"))
    report_dir.mkdir(parents=True, exist_ok=True)
    accepted_hash = str(command.get("accepted_state_sha256") or "")
    rollout_config = command.get("rollout")
    if not isinstance(rollout_config, dict):
        raise ValueError("rollout")
    target_name = str(rollout_config.get("timeline_name") or "")
    if target_name != FINAL_TIMELINE_NAME:
        raise ValueError("target_timeline_name")

    report: Dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "backend": "media_pool_append_plus_import_fusion_comp_full_lifecycle_rollout",
        "ok": False,
        "started_at": base.utc_now(),
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "final_timeline_name": target_name,
        "failures": [],
        "save_call_count": 0,
        "final_timeline_kept": False,
        "visual_review_required": False,
    }
    original_name = ""
    original_page = str(base.safe_value(resolve, "GetCurrentPage", default="") or "")
    target_created = False

    try:
        source_contract = base.verify_source_contract(root, command)
        report["source_contract_verified_count"] = source_contract["verified_count"]
        base.write_json(report_dir / "source_contract_verification.json", source_contract)

        accepted_path = root / ACCEPTED_STATE_RELATIVE_PATH
        if not accepted_path.is_file() or base.raw_sha256(accepted_path) != accepted_hash:
            raise RuntimeError("accepted_state")

        lifecycle = load_json(root / LIFECYCLE_AUTHORITY_RELATIVE_PATH)
        word_tracks = load_json(root / WORD_TRACKS_RELATIVE_PATH)
        redetection = load_json(root / LIFECYCLE_REDETECTION_RELATIVE_PATH)
        animations = load_json(root / ANIMATION_TARGETS_RELATIVE_PATH)
        controller = load_json(root / SOURCE_CONTROLLER_REPORT_RELATIVE_PATH)
        plan = compile_rollout_plan(lifecycle, word_tracks, controller, animations)
        if not plan.get("ok"):
            raise RuntimeError("rollout_plan")
        special_plans = {
            "come": visual.build_come_exit_plan(redetection),
            "they": visual.select_they_visual_instance(word_tracks, visual.COME_SOURCE["target_range"]),
        }
        if not special_plans["come"].get("ok") or not special_plans["they"].get("ok"):
            raise RuntimeError("special_visual_plans")
        plan_artifact = dict(plan)
        plan_artifact["special_plans"] = special_plans
        base.write_json(report_dir / "rollout_plan.json", plan_artifact)

        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        before_timelines = base.project_timeline_snapshot(project)
        original_name = str((before_timelines.get("current") or {}).get("name") or "")
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        if base.find_timeline(project, target_name) is not None:
            raise RuntimeError("target_timeline_exists")
        source_unique_id = base.timeline_unique_id(source)
        source_captions = base.caption_items(source)
        if len(source_captions) != EXPECTED_SOURCE_CAPTION_COUNT:
            raise RuntimeError(f"source_caption_count:{len(source_captions)}")

        source_before = source_snapshot(source, plan)
        base.write_json(report_dir / "source_inventory_before.json", source_before)
        report["source_inventory_ok"] = source_before.get("ok") is True
        report["source_range_policy"] = source_before.get("range_policy")
        report["source_range_adjustment_count"] = source_before.get("range_adjustment_count")
        report["source_range_adjustment_cue_ids"] = source_before.get("range_adjustment_cue_ids")
        if not source_before.get("ok"):
            raise RuntimeError("source_inventory")
        source_base_inventory = non_caption_inventory(source)
        carrier_source = base.choose_carrier_source(
            source,
            max(int(row["carrier_range"][1]) - int(row["carrier_range"][0]) for row in plan["instances"])
            + APPEND_SOURCE_END_PADDING_FRAMES,
        )
        if not carrier_source.get("ok"):
            raise RuntimeError("carrier_source")

        opened_edit, open_page_call = base.direct_call(resolve, "OpenPage", "edit")
        if not opened_edit:
            raise RuntimeError("open_edit_page")
        preflight = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "resolve_calls": resolve_calls,
            "open_page_call": open_page_call,
            "original_page": original_page,
            "original_timeline_name": original_name,
            "before_timelines": before_timelines,
            "source_timeline": {"name": SOURCE_TIMELINE_NAME, "unique_id": source_unique_id},
            "source_caption_count": len(source_captions),
            "source_base_item_count": len(source_base_inventory),
            "visual_instance_count": plan["summary"]["visual_instance_count"],
            "lane_count": plan["summary"]["lane_count"],
            "accepted_state_sha256": accepted_hash,
            "carrier_source": {key: base.json_safe(value) for key, value in carrier_source.items() if key not in {"item", "media_pool_item"}},
        }
        base.write_json(report_dir / "rollout_preflight.json", preflight)

        export_dir = report_dir / "source_comp_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        export_rows = []
        export_paths: Dict[str, Path] = {}
        source_signatures: Dict[str, Dict[str, Any]] = {}
        source_by_cue = {row["cue_id"]: row for row in source_before["rows"]}
        for index, instance in enumerate(plan["instances"], start=1):
            cue_id = str(instance["style_source_cue_id"])
            if cue_id in export_paths:
                continue
            track, source_item = base.find_named_item(source, instance["source_name"])
            if source_item is None:
                raise RuntimeError(f"source_item:{cue_id}")
            comp_path = export_dir / f"{cue_id}.comp"
            value, call = base.direct_call(source_item, "ExportFusionComp", str(comp_path), 1)
            file_ok = bool(value and comp_path.is_file() and comp_path.stat().st_size > 0)
            row = {
                "cue_id": cue_id,
                "name": instance["source_name"],
                "track": track,
                "path": str(comp_path),
                "size": comp_path.stat().st_size if comp_path.is_file() else 0,
                "sha256": base.raw_sha256(comp_path) if file_ok else None,
                "call": call,
                "ok": file_ok,
            }
            export_rows.append(row)
            base.write_json(report_dir / "source_comp_exports.json", {"rows": export_rows, "exported_count": len(export_rows), "ok": all(item["ok"] for item in export_rows)})
            if not file_ok:
                raise RuntimeError(f"source_comp_export:{cue_id}")
            export_paths[cue_id] = comp_path
            source_signatures[cue_id] = dict((source_by_cue[cue_id].get("signature") or {}).get("values") or {})
        if len(export_rows) != EXPECTED_INSTANCE_COUNT:
            raise RuntimeError(f"source_comp_export_count:{len(export_rows)}")

        duplicate_value, duplicate_call = base.direct_call(source, "DuplicateTimeline", target_name)
        target = duplicate_value if duplicate_value is not None else base.find_timeline(project, target_name)
        if target is None:
            raise RuntimeError("duplicate_timeline")
        target_created = True
        selected, select_call = base.direct_call(project, "SetCurrentTimeline", target)
        if not selected:
            raise RuntimeError("select_target")
        before_delete = base.caption_items(target)
        deletion = base.delete_items(target, [item for _, item in before_delete])
        time.sleep(0.20)
        after_delete = base.caption_items(target)
        track_setup = base.ensure_video_tracks(target, CAPTION_TRACK_BASE + EXPECTED_LANE_COUNT - 1)
        target_base_inventory = non_caption_inventory(target)
        base_inventory_comparison = compare_non_caption_inventory(
            source_base_inventory,
            target_base_inventory,
        )
        base_inventory_ok = base_inventory_comparison["ok"]
        setup = {
            "duplicate_call": duplicate_call,
            "select_call": select_call,
            "target_name": base.timeline_name(target),
            "target_unique_id": base.timeline_unique_id(target),
            "caption_count_before_delete": len(before_delete),
            "caption_delete": deletion,
            "caption_count_after_delete": len(after_delete),
            "track_setup": track_setup,
            "source_base_inventory": source_base_inventory,
            "target_base_inventory_after_caption_delete": target_base_inventory,
            "base_inventory_comparison": base_inventory_comparison,
            "base_inventory_unchanged": base_inventory_ok,
            "ok": bool(deletion.get("ok") and not after_delete and track_setup.get("ok") and base_inventory_ok),
        }
        base.write_json(report_dir / "duplicate_timeline_setup.json", setup)
        if not setup["ok"]:
            raise RuntimeError("duplicate_timeline_setup")

        carrier_resolution = resolve_base_carrier_collisions(plan["instances"], target_base_inventory)
        plan["instances"] = carrier_resolution["instances"]
        plan["summary"]["carrier_track_usage"] = carrier_resolution["carrier_track_usage"]
        plan["summary"]["carrier_overlap_count"] = len(carrier_resolution["carrier_overlaps"])
        plan["carrier_overlaps"] = carrier_resolution["carrier_overlaps"]
        plan["base_collision_resolution"] = {
            key: value
            for key, value in carrier_resolution.items()
            if key != "instances"
        }
        plan_artifact = dict(plan)
        plan_artifact["special_plans"] = special_plans
        base.write_json(report_dir / "rollout_plan.json", plan_artifact)

        append_audit = audit_append_payloads(plan["instances"], target_base_inventory, carrier_source)
        carrier_plan_audit = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "base_collision_resolution": {
                key: value
                for key, value in carrier_resolution.items()
                if key != "instances"
            },
            "append_payload_audit": append_audit,
            "ok": bool(carrier_resolution.get("ok") and append_audit.get("ok")),
        }
        base.write_json(report_dir / "carrier_plan_audit.json", carrier_plan_audit)
        if not carrier_plan_audit["ok"]:
            raise RuntimeError("carrier_plan_audit")

        specs = append_specs(plan["instances"])
        batches = batch_rows(specs)
        assigned_by_name: Dict[str, Any] = {}
        append_rows = []
        for batch_index, batch in enumerate(batches, start=1):
            result = append_batch_by_placement(media_pool, target, carrier_source, batch)
            append_rows.append({
                "batch_index": batch_index,
                "track": int(batch[0].get("carrier_track", batch[0]["target_track"])),
                "requested_count": result["requested_count"],
                "returned_count": result["returned_count"],
                "detected_count": result["detected_count"],
                "candidate_count": result["candidate_count"],
                "assigned_count": result["assigned_count"],
                "call": result["call"],
                "clip_infos": result["clip_infos"],
                "candidates": result["candidates"],
                "rows": result["rows"],
                "ok": result["ok"],
            })
            for spec, item in result["assigned"]:
                assigned_by_name[spec["name"]] = item
            base.write_json(report_dir / "carrier_append_progress.json", {
                "batch_count": len(batches),
                "completed_batch_count": len(append_rows),
                "assigned_count": len(assigned_by_name),
                "batches": append_rows,
                "ok": len(append_rows) == len(batches) and all(row["ok"] for row in append_rows),
            })
            if not result.get("ok"):
                raise RuntimeError(f"carrier_append_batch:{batch_index}")
        if len(assigned_by_name) != EXPECTED_INSTANCE_COUNT:
            raise RuntimeError(f"carrier_append_count:{len(assigned_by_name)}")

        imports = []
        applications = []
        application_by_name: Dict[str, Dict[str, Any]] = {}
        for index, instance in enumerate(plan["instances"], start=1):
            target_item = assigned_by_name[instance["target_name"]]
            cue_id = str(instance["style_source_cue_id"])
            clone = media.import_source_comp(target_item, export_paths[cue_id])
            imports.append({
                "index": index,
                "instance_id": instance["instance_id"],
                "target_name": instance["target_name"],
                "style_source_cue_id": cue_id,
                "clone": clone,
                "ok": clone.get("ok") is True,
            })
            base.write_json(report_dir / "comp_import_progress.json", {
                "expected_count": EXPECTED_INSTANCE_COUNT,
                "completed_count": len(imports),
                "rows": imports,
                "ok": len(imports) == EXPECTED_INSTANCE_COUNT and all(row["ok"] for row in imports),
            })
            if not clone.get("ok"):
                raise RuntimeError(f"fusion_import:{instance['instance_id']}")
            application = apply_instance(target_item, instance, special_plans)
            application_by_name[instance["target_name"]] = application
            applications.append({
                "index": index,
                "instance_id": instance["instance_id"],
                "target_name": instance["target_name"],
                "profile": instance["correction_profile"],
                "application": application,
                "ok": application.get("ok") is True,
            })
            base.write_json(report_dir / "correction_application_progress.json", {
                "expected_count": EXPECTED_INSTANCE_COUNT,
                "completed_count": len(applications),
                "rows": applications,
                "ok": len(applications) == EXPECTED_INSTANCE_COUNT and all(row["ok"] for row in applications),
            })
            if not application.get("ok"):
                raise RuntimeError(f"instance_application:{instance['instance_id']}")

        save = base.save_project(project_manager)
        report["save_call_count"] += 1 if save.get("success") else 0
        if not save.get("success"):
            raise RuntimeError("save_rollout")

        project_manager, project, media_pool, reacquire_calls = base.get_project(resolve)
        target_after = base.find_timeline(project, target_name)
        source_after = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if target_after is None or source_after is None:
            raise RuntimeError("timeline_reacquire")

        source_after_snapshot = source_snapshot(source_after, plan)
        source_unchanged = bool(
            base.timeline_unique_id(source_after) == source_unique_id
            and stable_source_snapshot(source_before) == stable_source_snapshot(source_after_snapshot)
        )
        accepted_unchanged = accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash
        final_base_inventory = non_caption_inventory(target_after)
        final_base_inventory_comparison = compare_non_caption_inventory(
            source_base_inventory,
            final_base_inventory,
        )
        base_unchanged = final_base_inventory_comparison["ok"]

        persistent_rows = []
        for instance in plan["instances"]:
            persistent_rows.append(persistent_instance_readback(
                target_after,
                instance,
                source_signatures[str(instance["style_source_cue_id"])],
                application_by_name[instance["target_name"]],
                special_plans,
            ))
            base.write_json(report_dir / "persistent_readback_progress.json", {
                "expected_count": EXPECTED_INSTANCE_COUNT,
                "completed_count": len(persistent_rows),
                "ok_count": sum(1 for row in persistent_rows if row.get("ok")),
                "rows": persistent_rows,
                "ok": len(persistent_rows) == EXPECTED_INSTANCE_COUNT and all(row.get("ok") for row in persistent_rows),
            })
        overlap_audit = timeline_overlap_audit(target_after, plan["instances"])
        persistent_ok = bool(len(persistent_rows) == EXPECTED_INSTANCE_COUNT and all(row.get("ok") for row in persistent_rows))
        animated_ok = sum(1 for row in persistent_rows if (row.get("animation") or {}).get("selected") and (row.get("animation") or {}).get("ok")) == EXPECTED_ANIMATED_COUNT
        special_ok = all(
            row.get("ok")
            for row in persistent_rows
            if row.get("instance_id") in {"sub_052", "visual_instance_sub_051_sub_054"}
        )
        final = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "checked_at": base.utc_now(),
            "reacquire_calls": reacquire_calls,
            "instance_count": len(persistent_rows),
            "ok_count": sum(1 for row in persistent_rows if row.get("ok")),
            "animated_verified_count": sum(1 for row in persistent_rows if (row.get("animation") or {}).get("selected") and (row.get("animation") or {}).get("ok")),
            "special_corrections_verified": special_ok,
            "instances": persistent_rows,
            "overlap_audit": overlap_audit,
            "source_before": source_before,
            "source_after": source_after_snapshot,
            "source_timeline_unchanged": source_unchanged,
            "accepted_state_unchanged": accepted_unchanged,
            "base_timeline_structure_unchanged": base_unchanged,
            "base_timeline_structure_comparison": final_base_inventory_comparison,
            "final_timeline_kept": True,
            "save": save,
            "ok": bool(persistent_ok and animated_ok and special_ok and overlap_audit.get("ok") and source_unchanged and accepted_unchanged and base_unchanged),
        }
        base.write_json(report_dir / "persistent_readback.json", final)
        if not final["ok"]:
            raise RuntimeError("persistent_rollout_readback")

        report.update({
            "ok": True,
            "finished_at": base.utc_now(),
            "source_caption_count": EXPECTED_SOURCE_CAPTION_COUNT,
            "source_inventory_ok": True,
            "source_range_policy": source_before["range_policy"],
            "source_range_adjustment_count": source_before["range_adjustment_count"],
            "source_range_adjustment_cue_ids": source_before["range_adjustment_cue_ids"],
            "source_comp_export_count": len(export_rows),
            "visual_instance_count": EXPECTED_INSTANCE_COUNT,
            "represented_cue_count": EXPECTED_ALIAS_COVERAGE,
            "merge_group_count": 1,
            "merged_aliases": ["sub_051", "sub_054"],
            "lane_count": EXPECTED_LANE_COUNT,
            "lane_usage": plan["summary"]["lane_usage"],
            "one_frame_carrier_count": plan["summary"]["one_frame_carrier_count"],
            "one_frame_carrier_ids": plan["summary"]["one_frame_carrier_ids"],
            "base_collision_relocation_count": carrier_resolution["relocation_count"],
            "base_collision_relocation_ids": carrier_resolution["relocation_ids"],
            "base_collision_relocations": carrier_resolution["relocations"],
            "carrier_plan_audit_ok": carrier_plan_audit["ok"],
            "carrier_track_usage": carrier_resolution["carrier_track_usage"],
            "carrier_overlap_count": len(carrier_resolution["carrier_overlaps"]),
            "carrier_base_collision_count": len(carrier_resolution["remaining_base_collisions"]),
            "append_batch_count": len(batches),
            "carrier_append_count": len(assigned_by_name),
            "comp_import_count": len(imports),
            "instance_application_count": len(applications),
            "persistent_instance_count": len(persistent_rows),
            "exact_lifecycle_instance_count": sum(1 for row in persistent_rows if row.get("exact_duration_ok")),
            "append_source_end_padding_frames": APPEND_SOURCE_END_PADDING_FRAMES,
            "animated_instance_count": EXPECTED_ANIMATED_COUNT,
            "animated_verified_count": final["animated_verified_count"],
            "same_track_overlap_count": len(overlap_audit["same_track_overlaps"]),
            "special_corrections_verified": special_ok,
            "source_timeline_unchanged": source_unchanged,
            "accepted_state_unchanged": accepted_unchanged,
            "base_timeline_structure_unchanged": base_unchanged,
            "final_timeline_kept": True,
            "final_timeline_unique_id": base.timeline_unique_id(target_after),
            "visual_review_required": True,
            "visual_review_windows": [
                {"cue_id": "sub_019", "range": [246, 266]},
                {"cue_id": "sub_052+sub_051+sub_054", "range": [428, 452]},
                {"cue_id": "sub_057+sub_058", "range": [454, 493]},
                {"cue_id": "sub_073_one_frame_carrier", "range": [520, 524]},
                {"cue_id": "sub_065", "range": [487, 497]},
                {"cue_id": "sub_078+sub_081", "range": [624, 656]},
                {"cue_id": "sub_116", "range": [894, 906]},
            ],
            "visual_review_instruction": (
                f"Open {target_name}. Review the listed animation/overlap windows, then scrub the complete timeline. "
                "Confirm 115 editable visual instances represent all 116 transcript cues; the merged lower-case they "
                "stays above COME; COME retains the accepted style and rightward fade; all other captions preserve "
                "the protected source style/position and calibrated lifecycle windows. Confirm sub_073 is visible only "
                "at frame 521 even though its minimum appendable carrier spans frames 521-522 on V4. Confirm COME remains correct on its relocated physical carrier V7 while the preserved V4 occlusion matte remains unchanged."
            ),
        })
        base.write_json(report_dir / "rollout_result.json", report)
        return report

    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc))
        report["traceback"] = traceback.format_exc()
        cleanup = cleanup_target(
            resolve,
            target_name,
            original_name or SOURCE_TIMELINE_NAME,
            original_page,
            root,
            accepted_hash,
        ) if target_created else {
            "attempted": False,
            "probe_deleted": True,
            "accepted_state_unchanged": (
                (root / ACCEPTED_STATE_RELATIVE_PATH).is_file()
                and base.raw_sha256(root / ACCEPTED_STATE_RELATIVE_PATH) == accepted_hash
            ),
            "ok": True,
        }
        if cleanup.get("save_cleanup", {}).get("success"):
            report["save_call_count"] += 1
        report.update({
            "ok": False,
            "finished_at": base.utc_now(),
            "cleanup": cleanup,
            "final_timeline_kept": False,
            "visual_review_required": False,
            "accepted_state_unchanged": cleanup.get("accepted_state_unchanged"),
        })
        base.write_json(report_dir / "rollout_cleanup.json", cleanup)
        base.write_json(report_dir / "rollout_result.json", report)
        return report
