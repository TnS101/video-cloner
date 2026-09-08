"""Stabilize the merged ``they`` instance and source-match COME styling.

The retained V2 proof established the working Resolve route and correct relative
layout. This bounded correction preserves that architecture while addressing only
the two user-rejected visual details:

* remove ``they`` shimmer by replacing noisy frame-to-frame detector variation
  with a monotonic entrance/exit and a fixed source-median hold;
* match COME to the baked source glyph using a source-frame measured fill, no
  outline/shadow, and the observed 2x glyph-size correction.

A fresh disposable proof timeline is created and retained only on PASS.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import statistics
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

MEDIA_BASE_PATH = Path(__file__).with_name("step_3D_media_backed_fusion_clone.py")
_spec = importlib.util.spec_from_file_location("vc_media_fusion_clone_v1", MEDIA_BASE_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot_load:{MEDIA_BASE_PATH}")
media = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = media
_spec.loader.exec_module(media)
base = media.base

TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_INSTANCE_CORRECTION_V3"
MODE = "STEP_3D_VISUAL_INSTANCE_CORRECTION"
MODULE_RELATIVE_PATH = "resolve_workspace/modules/step_3D_visual_instance_correction.py"
SOURCE_TIMELINE_NAME = base.SOURCE_TIMELINE_NAME
EXPECTED_SOURCE_CAPTION_COUNT = base.EXPECTED_SOURCE_CAPTION_COUNT
ACCEPTED_STATE_RELATIVE_PATH = base.ACCEPTED_STATE_RELATIVE_PATH
SOURCE_HASH_ALGORITHM = base.SOURCE_HASH_ALGORITHM
WORD_TRACKS_RELATIVE_PATH = (
    "data/DZsqH7auhjt/analysis/"
    "DZsqH7auhjt_caption_word_instance_tracks_step_3B_6B.json"
)
LIFECYCLE_REDETECTION_RELATIVE_PATH = (
    "data/DZsqH7auhjt/analysis/"
    "DZsqH7auhjt_caption_lifecycle_redetection_step_3D.json"
)

COME_SOURCE = {
    "cue_id": "sub_052",
    "name": "VC_TEXTPLUS_0052_sub_052",
    "text": "COME",
    "source_range": [430, 434],
    "target_range": [430, 452],
    "target_track": 3,
}
THEY_STYLE_SOURCE = {
    "cue_id": "sub_051",
    "name": "VC_TEXTPLUS_0051_sub_051",
    "text": "THEY",
    "source_range": [426, 430],
}
THEY_TARGET_NAME = "VC_TEXTPLUS_VISUAL_INSTANCE_THEY_sub_051_sub_054"
COME_HOLD_CENTER = [0.5, 0.6276]
THEY_HOLD_START = 435
THEY_HOLD_END = 449
# Source frame 430 and the V2 proof show the imported protected comp at almost
# exactly half the baked glyph width. The non-occluded C/E interiors cluster at
# RGB (39, 43, 48). These values intentionally supersede the visually rejected
# Step 3B fill/outline estimate for this one proof boundary.
COME_SOURCE_FRAME_STYLE = {
    "Size": 0.232061530556,
    "Red1": 39.0 / 255.0,
    "Green1": 43.0 / 255.0,
    "Blue1": 48.0 / 255.0,
    "Enabled2": 0.0,
    "Thickness2": 0.0,
    "Enabled3": 0.0,
}
FRAME_TOLERANCE = 1e-5
POINT_TOLERANCE = 0.003


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def normalize_token(value: Any) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def median(values: Iterable[float], default: float = 0.0) -> float:
    rows = [float(value) for value in values]
    return float(statistics.median(rows)) if rows else float(default)


def track_bounds(track: Dict[str, Any]) -> Tuple[int, int]:
    geometry = track.get("geometry") if isinstance(track.get("geometry"), dict) else {}
    first = int(geometry.get("first_visible_frame"))
    last = int(geometry.get("last_visible_frame"))
    return first, last


def track_center(track: Dict[str, Any]) -> List[float]:
    observations = track.get("frame_observations") if isinstance(track.get("frame_observations"), list) else []
    xs = []
    ys = []
    for observation in observations:
        position = observation.get("position") if isinstance(observation, dict) else None
        if isinstance(position, (list, tuple)) and len(position) >= 2:
            xs.append(float(position[0]))
            ys.append(float(position[1]))
    return [median(xs), median(ys)]


def same_visual_instance(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    if normalize_token(left.get("text")) != normalize_token(right.get("text")):
        return False
    left_first, left_last = track_bounds(left)
    right_first, right_last = track_bounds(right)
    if right_first < left_first:
        left, right = right, left
        left_first, left_last, right_first, right_last = right_first, right_last, left_first, left_last
    if right_first - left_last > 1:
        return False
    left_center = track_center(left)
    right_center = track_center(right)
    if math.dist(left_center, right_center) > 0.035:
        return False
    left_geometry = left.get("geometry") or {}
    right_geometry = right.get("geometry") or {}
    for key in ("median_bbox_width_px", "median_bbox_height_px"):
        a = float(left_geometry.get(key) or 0.0)
        b = float(right_geometry.get(key) or 0.0)
        if a <= 0.0 or b <= 0.0 or abs(a - b) / max(a, b) > 0.15:
            return False
    return True


def deduplicated_tracks(document: Dict[str, Any], token: str) -> List[Dict[str, Any]]:
    tracks = document.get("tracks") if isinstance(document.get("tracks"), list) else []
    rows = []
    seen = set()
    for track in tracks:
        if not isinstance(track, dict):
            continue
        if normalize_token(track.get("text")) != token:
            continue
        if track.get("accepted_source_instance") is not True:
            continue
        observations = track.get("frame_observations")
        if not isinstance(observations, list) or not observations:
            continue
        key = str(track.get("cue_id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(track)
    return sorted(rows, key=lambda row: (*track_bounds(row), str(row.get("cue_id") or "")))


def merge_observations(tracks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_frame: Dict[int, Dict[str, Any]] = {}
    for track in tracks:
        for observation in track.get("frame_observations") or []:
            if not isinstance(observation, dict):
                continue
            frame = int(observation.get("timeline_frame"))
            previous = by_frame.get(frame)
            score = float(observation.get("opacity_proxy") or 0.0)
            previous_score = float((previous or {}).get("opacity_proxy") or 0.0)
            if previous is None or score > previous_score:
                by_frame[frame] = dict(observation)
    return [by_frame[frame] for frame in sorted(by_frame)]


def stabilize_they_animation(
    position_keys: Sequence[Dict[str, Any]],
    opacity_keys: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Remove detector jitter without changing the observed lifecycle.

    Dense keys are retained at every frame so Resolve does not invent spline
    overshoot. Only noisy sub-pixel hold movement and non-monotonic opacity
    fluctuations are removed.
    """
    positions = [dict(row) for row in position_keys]
    opacities = [dict(row) for row in opacity_keys]
    if not positions or len(positions) != len(opacities):
        raise RuntimeError("they_stabilization_contract")
    position_frames = [int(row["timeline_frame"]) for row in positions]
    opacity_frames = [int(row["timeline_frame"]) for row in opacities]
    if position_frames != opacity_frames:
        raise RuntimeError("they_stabilization_frames")

    hold_rows = [
        row for row in positions
        if THEY_HOLD_START <= int(row["timeline_frame"]) < THEY_HOLD_END
    ]
    if not hold_rows:
        raise RuntimeError("they_stabilization_hold")
    stable_x = median(float(row["value"][0]) for row in hold_rows)
    stable_y = median(float(row["value"][1]) for row in positions)

    stabilized_positions: List[Dict[str, Any]] = []
    previous_x = -math.inf
    for row in positions:
        frame = int(row["timeline_frame"])
        raw_x = float(row["value"][0])
        if THEY_HOLD_START <= frame < THEY_HOLD_END:
            x = stable_x
        else:
            x = max(previous_x, raw_x)
        previous_x = x
        stabilized_positions.append({
            **row,
            "value": [float(x), float(stable_y)],
            "raw_value": list(row["value"]),
        })

    stabilized_opacities: List[Dict[str, Any]] = []
    entrance_max = 0.0
    exit_min = 1.0
    for row in opacities:
        frame = int(row["timeline_frame"])
        raw_factor = max(0.0, min(1.0, float(row["factor"])))
        if frame < THEY_HOLD_START:
            entrance_max = max(entrance_max, raw_factor)
            factor = entrance_max
        elif frame < THEY_HOLD_END:
            factor = 1.0
        else:
            exit_min = min(exit_min, raw_factor)
            factor = exit_min
        stabilized_opacities.append({
            **row,
            "factor": float(factor),
            "raw_factor": raw_factor,
        })

    hold_positions = [
        row["value"] for row in stabilized_positions
        if THEY_HOLD_START <= int(row["timeline_frame"]) < THEY_HOLD_END
    ]
    hold_opacities = [
        float(row["factor"]) for row in stabilized_opacities
        if THEY_HOLD_START <= int(row["timeline_frame"]) < THEY_HOLD_END
    ]
    entrance_factors = [
        float(row["factor"]) for row in stabilized_opacities
        if int(row["timeline_frame"]) < THEY_HOLD_START
    ]
    exit_factors = [
        float(row["factor"]) for row in stabilized_opacities
        if int(row["timeline_frame"]) >= THEY_HOLD_END
    ]
    metadata = {
        "policy": "dense_monotonic_entrance_exit_fixed_source_median_hold",
        "hold_window": [THEY_HOLD_START, THEY_HOLD_END],
        "hold_center": [float(stable_x), float(stable_y)],
        "position_key_count": len(stabilized_positions),
        "opacity_key_count": len(stabilized_opacities),
        "ok": bool(
            hold_positions
            and all(value == hold_positions[0] for value in hold_positions)
            and hold_opacities
            and all(abs(value - 1.0) <= FRAME_TOLERANCE for value in hold_opacities)
            and entrance_factors == sorted(entrance_factors)
            and exit_factors == sorted(exit_factors, reverse=True)
        ),
    }
    return stabilized_positions, stabilized_opacities, metadata


def select_they_visual_instance(document: Dict[str, Any], come_window: Sequence[int]) -> Dict[str, Any]:
    candidates = deduplicated_tracks(document, "they")
    groups: List[List[Dict[str, Any]]] = []
    for candidate in candidates:
        if not groups or not same_visual_instance(groups[-1][-1], candidate):
            groups.append([candidate])
        else:
            groups[-1].append(candidate)

    start, end = [int(value) for value in come_window]
    scored = []
    for group in groups:
        first = min(track_bounds(row)[0] for row in group)
        last = max(track_bounds(row)[1] for row in group)
        overlap = max(0, min(last + 1, end) - max(first, start))
        spans_entry = first <= start
        spans_exit = last >= end - 1
        scored.append(((int(spans_entry), int(spans_exit), overlap, -first), group))
    if not scored:
        raise RuntimeError("they_visual_instance_missing")
    score, selected = max(scored, key=lambda row: row[0])
    if score[0] != 1 or score[1] != 1:
        raise RuntimeError("they_visual_instance_incomplete")

    observations = merge_observations(selected)
    first = min(int(row["timeline_frame"]) for row in observations)
    last = max(int(row["timeline_frame"]) for row in observations)
    aliases = [str(row.get("cue_id") or "") for row in selected]
    style_source = min(selected, key=lambda row: track_bounds(row)[0])
    position_keys = []
    opacity_keys = []
    for observation in observations:
        position = observation.get("position")
        if not isinstance(position, (list, tuple)) or len(position) < 2:
            raise RuntimeError("they_position_observation")
        frame = int(observation["timeline_frame"])
        position_keys.append({
            "timeline_frame": frame,
            "local_frame": frame - first,
            "value": [float(position[0]), 1.0 - float(position[1])],
        })
        opacity_keys.append({
            "timeline_frame": frame,
            "local_frame": frame - first,
            "factor": max(0.0, min(1.0, float(observation.get("opacity_proxy") or 0.0))),
        })

    position_keys, opacity_keys, stabilization = stabilize_they_animation(position_keys, opacity_keys)

    return {
        "token": "they",
        "source_cue_ids": aliases,
        "style_source_cue_id": str(style_source.get("cue_id") or ""),
        "style_source_name": str(style_source.get("name") or THEY_STYLE_SOURCE["name"]),
        "visual_window": [first, last + 1],
        "position_keys": position_keys,
        "opacity_keys": opacity_keys,
        "stabilization": stabilization,
        "candidate_count": len(candidates),
        "group_count": len(groups),
        "selected_group_size": len(selected),
        "selection_basis": (
            "same normalized text + contiguous frames + matching median geometry + "
            "coverage of COME entry and exit"
        ),
        "ok": bool(
            aliases == ["sub_051", "sub_054"]
            and [first, last + 1] == [428, 452]
            and stabilization.get("ok")
        ),
    }


def detection_for(document: Dict[str, Any], cue_id: str) -> Dict[str, Any]:
    detections = document.get("detections") if isinstance(document.get("detections"), list) else []
    for detection in detections:
        if isinstance(detection, dict) and detection.get("cue_id") == cue_id:
            return detection
    raise RuntimeError(f"detection_missing:{cue_id}")


def source_center_from_match(
    observation: Dict[str, Any],
    search_bbox: Sequence[float],
    width: int,
    height: int,
) -> List[float]:
    location = observation.get("match_location_in_search")
    size = observation.get("match_size")
    if not isinstance(location, (list, tuple)) or len(location) < 2:
        raise RuntimeError("match_location")
    if not isinstance(size, (list, tuple)) or len(size) < 2:
        raise RuntimeError("match_size")
    source_x = float(search_bbox[0]) + float(location[0]) + float(size[0]) / 2.0
    source_y = float(search_bbox[1]) + float(location[1]) + float(size[1]) / 2.0
    return [source_x / float(width), 1.0 - source_y / float(height)]


def build_come_exit_plan(document: Dict[str, Any]) -> Dict[str, Any]:
    detection = detection_for(document, "sub_052")
    phases = detection.get("lifecycle_phases") if isinstance(detection.get("lifecycle_phases"), dict) else {}
    exit_start, exit_end = [int(value) for value in phases.get("exit") or []]
    if [exit_start, exit_end] != [448, 452]:
        raise RuntimeError("come_exit_window")
    source_seed = detection.get("source_seed") if isinstance(detection.get("source_seed"), dict) else {}
    search_bbox = source_seed.get("search_bbox_pixels")
    video_info = document.get("source_video_info") if isinstance(document.get("source_video_info"), dict) else {}
    width = int(video_info.get("width") or 0)
    height = int(video_info.get("height") or 0)
    if not isinstance(search_bbox, list) or len(search_bbox) < 4 or width <= 0 or height <= 0:
        raise RuntimeError("come_geometry_contract")

    observations = detection.get("observations") if isinstance(detection.get("observations"), list) else []
    by_frame: Dict[int, Dict[str, Any]] = {}
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        frame = int(observation.get("timeline_frame"))
        previous = by_frame.get(frame)
        if previous is None or int(observation.get("source_frame") or 0) > int(previous.get("source_frame") or 0):
            by_frame[frame] = observation

    hold_scores = [
        float(row.get("template_score") or 0.0)
        for frame, row in by_frame.items()
        if 440 <= frame < exit_start
    ]
    baseline_score = median(hold_scores)
    if baseline_score <= 0.0:
        raise RuntimeError("come_exit_baseline")

    center_keys = [{"timeline_frame": 447, "local_frame": 17, "value": list(COME_HOLD_CENTER)}]
    opacity_keys = [{"timeline_frame": 447, "local_frame": 17, "factor": 1.0}]
    for frame in range(exit_start, exit_end):
        observation = by_frame.get(frame)
        if observation is None:
            raise RuntimeError(f"come_exit_observation:{frame}")
        center_keys.append({
            "timeline_frame": frame,
            "local_frame": frame - COME_SOURCE["target_range"][0],
            "value": source_center_from_match(observation, search_bbox, width, height),
        })
        factor = float(observation.get("template_score") or 0.0) / baseline_score
        opacity_keys.append({
            "timeline_frame": frame,
            "local_frame": frame - COME_SOURCE["target_range"][0],
            "factor": max(0.0, min(1.0, factor)),
        })

    return {
        "cue_id": "sub_052",
        "visual_window": list(detection.get("lifecycle_window") or []),
        "exit_window": [exit_start, exit_end],
        "center_keys": center_keys,
        "opacity_keys": opacity_keys,
        "baseline_template_score": baseline_score,
        "selection_basis": "targeted source-video template tracking; latest source observation per timeline frame",
        "ok": bool(
            len(center_keys) == 5
            and center_keys[-1]["value"][0] > center_keys[0]["value"][0] + 0.05
            and opacity_keys[-1]["factor"] < 0.6
        ),
    }


def connected_output(input_object: Any) -> Any:
    if input_object is None:
        return None
    try:
        return input_object.GetConnectedOutput()
    except BaseException:
        return None


def ensure_modifier(tool: Any, input_name: str, modifier_name: str) -> Dict[str, Any]:
    input_object = base.find_input(tool, input_name)
    if input_object is None:
        return {"ok": False, "created": False, "error": f"input_missing:{input_name}"}
    if connected_output(input_object) is not None:
        return {"ok": True, "created": False, "modifier": "existing"}
    returned, call = base.direct_call(tool, "AddModifier", input_name, modifier_name)
    time.sleep(0.05)
    connected = connected_output(base.find_input(tool, input_name)) is not None
    return {
        "ok": connected,
        "created": connected,
        "modifier": modifier_name,
        "returned": base.json_safe(returned),
        "call": call,
        "error": None if connected else f"modifier_not_connected:{input_name}",
    }


def scalar_matches(actual: Any, expected: float, tolerance: float = FRAME_TOLERANCE) -> bool:
    try:
        return abs(float(actual) - float(expected)) <= tolerance
    except (TypeError, ValueError):
        return False


def value_matches(input_name: str, actual: Any, expected: Any) -> bool:
    if input_name == "Center":
        return base.point_matches(actual, list(expected), tolerance=POINT_TOLERANCE)
    if input_name == "StyledText":
        return str(actual or "") == str(expected)
    return scalar_matches(actual, float(expected), tolerance=1e-4)


def write_key(tool: Any, input_name: str, frame: int, expected: Any) -> Dict[str, Any]:
    input_object = base.find_input(tool, input_name)
    variants = [expected]
    if input_name == "Center":
        x, y = [float(value) for value in expected]
        variants = [{1: x, 2: y, 3: 0.0}, {1: x, 2: y}, [x, y]]
    attempts = []
    for variant in variants:
        if input_object is not None:
            try:
                input_object[int(frame)] = variant
                actual = base.read_input(tool, input_name, int(frame))
                matched = value_matches(input_name, actual, expected)
                attempts.append({"method": "Input[frame]", "variant": base.json_safe(variant), "matched": matched})
                if matched:
                    return {"ok": True, "attempts": attempts, "actual": base.json_safe(actual)}
            except BaseException as exc:
                attempts.append({"method": "Input[frame]", "error": base.compact_exception(exc)})
        try:
            returned = tool.SetInput(input_name, variant, int(frame))
            actual = base.read_input(tool, input_name, int(frame))
            matched = value_matches(input_name, actual, expected)
            attempts.append({
                "method": "SetInput(name,value,frame)",
                "variant": base.json_safe(variant),
                "returned": base.json_safe(returned),
                "matched": matched,
            })
            if matched:
                return {"ok": True, "attempts": attempts, "actual": base.json_safe(actual)}
        except BaseException as exc:
            attempts.append({"method": "SetInput(name,value,frame)", "error": base.compact_exception(exc)})
    return {"ok": False, "attempts": attempts}


def set_static(tool: Any, input_name: str, value: Any) -> Dict[str, Any]:
    attempts = []
    try:
        returned = tool.SetInput(input_name, value)
        actual = base.read_input(tool, input_name, 0)
        matched = value_matches(input_name, actual, value)
        attempts.append({"returned": base.json_safe(returned), "actual": base.json_safe(actual), "matched": matched})
        return {"ok": matched, "attempts": attempts}
    except BaseException as exc:
        attempts.append({"error": base.compact_exception(exc)})
        return {"ok": False, "attempts": attempts}


def apply_static_inputs(tool: Any, values: Dict[str, float]) -> Dict[str, Any]:
    rows = []
    for input_name, expected in values.items():
        input_available = base.find_input(tool, input_name) is not None
        write = set_static(tool, input_name, expected) if input_available else {
            "ok": False,
            "error": f"input_missing:{input_name}",
        }
        rows.append({
            "input": input_name,
            "expected": float(expected),
            "input_available": input_available,
            "write": write,
            "ok": bool(input_available and write.get("ok")),
        })
    return {"values": dict(values), "rows": rows, "ok": bool(rows and all(row["ok"] for row in rows))}


def static_input_readback(tool: Any, values: Dict[str, float]) -> Dict[str, Any]:
    rows = []
    for input_name, expected in values.items():
        actual = base.read_input(tool, input_name, 0)
        rows.append({
            "input": input_name,
            "expected": float(expected),
            "actual": base.json_safe(actual),
            "matched": value_matches(input_name, actual, expected),
        })
    return {"rows": rows, "ok": bool(rows and all(row["matched"] for row in rows))}


def extend_comp_range(comp: Any, text_tool: Any, last_frame: int) -> Dict[str, Any]:
    attributes = {
        "COMPN_GlobalStart": 0,
        "COMPN_GlobalEnd": int(last_frame),
        "COMPN_RenderStart": 0,
        "COMPN_RenderEnd": int(last_frame),
    }
    returned, call = base.direct_call(comp, "SetAttrs", attributes)
    after = base.safe_value(comp, "GetAttrs", default={}) or {}
    global_out = set_static(text_tool, "GlobalOut", int(last_frame))
    attr_end = after.get("COMPN_GlobalEnd") if isinstance(after, dict) else None
    attrs_verified = attr_end is None or int(attr_end) >= int(last_frame)
    return {
        "requested_last_frame": int(last_frame),
        "set_attrs": call,
        "set_attrs_returned": base.json_safe(returned),
        "attrs_after": base.json_safe(after),
        "attrs_verified": attrs_verified,
        "global_out": global_out,
        "ok": bool(call.get("error") is None and attrs_verified and global_out.get("ok")),
    }


def base_layer_opacities(text_tool: Any) -> Dict[str, float]:
    defaults = {"Opacity1": 1.0, "Opacity2": 1.0, "Opacity3": 0.85}
    result = {}
    for name, default in defaults.items():
        if base.find_input(text_tool, name) is None:
            continue
        actual = base.read_input(text_tool, name, 0)
        try:
            result[name] = float(actual)
        except (TypeError, ValueError):
            result[name] = default
    return result


def apply_opacity_series(text_tool: Any, keys: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    base_values = base_layer_opacities(text_tool)
    rows = []
    for input_name, base_value in base_values.items():
        modifier = ensure_modifier(text_tool, input_name, "BezierSpline")
        input_rows = []
        if modifier.get("ok"):
            for key in keys:
                expected = base_value * float(key["factor"])
                write = write_key(text_tool, input_name, int(key["local_frame"]), expected)
                input_rows.append({
                    "timeline_frame": int(key["timeline_frame"]),
                    "local_frame": int(key["local_frame"]),
                    "factor": float(key["factor"]),
                    "expected": expected,
                    "write": write,
                })
        rows.append({
            "input": input_name,
            "base_value": base_value,
            "modifier": modifier,
            "keys": input_rows,
            "ok": bool(modifier.get("ok") and len(input_rows) == len(keys) and all(row["write"].get("ok") for row in input_rows)),
        })
    return {
        "base_values": base_values,
        "available_inputs": list(base_values),
        "skipped_inputs": [name for name in ("Opacity1", "Opacity2", "Opacity3") if name not in base_values],
        "rows": rows,
        "ok": bool(rows and all(row["ok"] for row in rows)),
    }


def apply_center_series(text_tool: Any, keys: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    modifier = ensure_modifier(text_tool, "Center", "Path")
    rows = []
    if modifier.get("ok"):
        for key in keys:
            write = write_key(text_tool, "Center", int(key["local_frame"]), key["value"])
            rows.append({**key, "write": write})
    return {
        "modifier": modifier,
        "keys": rows,
        "ok": bool(modifier.get("ok") and len(rows) == len(keys) and all(row["write"].get("ok") for row in rows)),
    }


def apply_come_correction(item: Any, plan: Dict[str, Any]) -> Dict[str, Any]:
    comp = base.get_comp(item)
    text_tool = base.get_text_tool(comp)
    if comp is None or text_tool is None:
        return {"ok": False, "error": "come_comp_or_text"}
    duration = COME_SOURCE["target_range"][1] - COME_SOURCE["target_range"][0]
    comp_range = extend_comp_range(comp, text_tool, duration - 1)
    style = apply_static_inputs(text_tool, COME_SOURCE_FRAME_STYLE)
    center = apply_center_series(text_tool, plan["center_keys"])
    opacity = apply_opacity_series(text_tool, plan["opacity_keys"])
    return {
        "comp_range": comp_range,
        "style": style,
        "center": center,
        "opacity": opacity,
        "ok": bool(comp_range["ok"] and style["ok"] and center["ok"] and opacity["ok"]),
    }


def apply_they_correction(item: Any, plan: Dict[str, Any]) -> Dict[str, Any]:
    comp = base.get_comp(item)
    text_tool = base.get_text_tool(comp)
    if comp is None or text_tool is None:
        return {"ok": False, "error": "they_comp_or_text"}
    duration = int(plan["visual_window"][1]) - int(plan["visual_window"][0])
    comp_range = extend_comp_range(comp, text_tool, duration - 1)
    text = set_static(text_tool, "StyledText", "they")
    center = apply_center_series(text_tool, plan["position_keys"])
    opacity = apply_opacity_series(text_tool, plan["opacity_keys"])
    return {
        "comp_range": comp_range,
        "text": text,
        "center": center,
        "opacity": opacity,
        "ok": bool(comp_range["ok"] and text["ok"] and center["ok"] and opacity["ok"]),
    }


def read_series(text_tool: Any, input_name: str, keys: Sequence[Dict[str, Any]], base_value: Optional[float] = None) -> List[Dict[str, Any]]:
    rows = []
    for key in keys:
        expected = key.get("value") if input_name == "Center" else float(base_value or 0.0) * float(key["factor"])
        actual = base.read_input(text_tool, input_name, int(key["local_frame"]))
        rows.append({
            "timeline_frame": int(key["timeline_frame"]),
            "local_frame": int(key["local_frame"]),
            "expected": base.json_safe(expected),
            "actual": base.json_safe(actual),
            "matched": value_matches(input_name, actual, expected),
        })
    return rows


def persistent_visual_readback(
    item: Any,
    text: str,
    center_keys: Sequence[Dict[str, Any]],
    opacity_keys: Sequence[Dict[str, Any]],
    opacity_base_values: Dict[str, float],
) -> Dict[str, Any]:
    comp = base.get_comp(item)
    text_tool = base.get_text_tool(comp)
    if comp is None or text_tool is None:
        return {"ok": False, "comp_available": False, "text_tool_available": False}
    actual_text = base.text_readback(text_tool)
    centers = read_series(text_tool, "Center", center_keys)
    opacity_rows = {}
    for name, base_value in opacity_base_values.items():
        opacity_rows[name] = read_series(text_tool, name, opacity_keys, base_value=base_value)
    return {
        "comp_available": True,
        "text_tool_available": True,
        "expected_text": text,
        "actual_text": actual_text,
        "text_matched": actual_text == text,
        "center_rows": centers,
        "center_matched": all(row["matched"] for row in centers),
        "opacity_rows": opacity_rows,
        "opacity_matched": all(all(row["matched"] for row in rows) for rows in opacity_rows.values()),
        "ok": bool(actual_text == text and all(row["matched"] for row in centers) and all(all(row["matched"] for row in rows) for rows in opacity_rows.values())),
    }


def source_identity(timeline: Any, specs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    for spec in specs:
        track, item = base.find_named_item(timeline, spec["name"])
        if item is None:
            rows.append({"name": spec["name"], "found": False})
            continue
        comp = base.get_comp(item)
        tool = base.get_text_tool(comp)
        rows.append({
            "name": spec["name"],
            "found": True,
            "summary": base.item_summary(int(track or 0), item),
            "text": base.text_readback(tool) if tool is not None else "",
        })
    return {"rows": rows}


def stable_source_identity(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    output = []
    for row in snapshot.get("rows") or []:
        summary = row.get("summary") or {}
        output.append({
            "name": row.get("name"),
            "found": row.get("found"),
            "unique_id": summary.get("unique_id"),
            "track_index": summary.get("track_index"),
            "start": summary.get("start"),
            "end": summary.get("end"),
            "fusion_comp_count": summary.get("fusion_comp_count"),
            "text": row.get("text"),
        })
    return output


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
    probe = command.get("probe")
    if not isinstance(probe, dict):
        raise ValueError("probe")
    probe_name = str(probe.get("timeline_name") or "")
    if not probe_name:
        raise ValueError("probe_timeline_name")

    report: Dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "backend": "media_pool_append_plus_import_fusion_comp_style_stabilization",
        "ok": False,
        "started_at": base.utc_now(),
        "probe_timeline_name": probe_name,
        "source_timeline_name": SOURCE_TIMELINE_NAME,
        "failures": [],
        "save_call_count": 0,
        "probe_timeline_kept": False,
        "visual_review_required": False,
    }
    original_name = ""
    original_page = str(base.safe_value(resolve, "GetCurrentPage", default="") or "")
    duplicate_created = False

    try:
        source_contract = base.verify_source_contract(root, command)
        report["source_contract_verified_count"] = source_contract["verified_count"]
        base.write_json(report_dir / "source_contract_verification.json", source_contract)

        accepted_path = root / ACCEPTED_STATE_RELATIVE_PATH
        if not accepted_path.is_file() or base.raw_sha256(accepted_path) != accepted_hash:
            raise RuntimeError("accepted_state")

        word_tracks = load_json(root / WORD_TRACKS_RELATIVE_PATH)
        lifecycle = load_json(root / LIFECYCLE_REDETECTION_RELATIVE_PATH)
        they_plan = select_they_visual_instance(word_tracks, COME_SOURCE["target_range"])
        come_plan = build_come_exit_plan(lifecycle)
        if not they_plan.get("ok") or not come_plan.get("ok"):
            raise RuntimeError("visual_instance_plan")
        target_specs = [
            dict(COME_SOURCE),
            {
                "cue_id": "visual_they_sub_051_sub_054",
                "name": THEY_TARGET_NAME,
                "text": "they",
                "source_range": list(THEY_STYLE_SOURCE["source_range"]),
                "target_range": list(they_plan["visual_window"]),
                "target_track": 5,
            },
        ]
        visual_plan = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "come": come_plan,
            "they": they_plan,
            "targets": target_specs,
            "ok": True,
        }
        base.write_json(report_dir / "visual_instance_plan.json", visual_plan)

        project_manager, project, media_pool, resolve_calls = base.get_project(resolve)
        before_timelines = base.project_timeline_snapshot(project)
        original_name = str((before_timelines.get("current") or {}).get("name") or "")
        source = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if source is None:
            raise RuntimeError("source_timeline")
        source_unique_id = base.timeline_unique_id(source)
        source_caption_rows = base.caption_items(source)
        if len(source_caption_rows) != EXPECTED_SOURCE_CAPTION_COUNT:
            raise RuntimeError(f"source_caption_count:{len(source_caption_rows)}")

        source_specs = [COME_SOURCE, THEY_STYLE_SOURCE]
        source_before = source_identity(source, source_specs)
        for spec, row in zip(source_specs, source_before["rows"]):
            if not row.get("found"):
                raise RuntimeError(f"source_item:{spec['cue_id']}")
            summary = row["summary"]
            if [summary["start"], summary["end"]] != spec["source_range"]:
                raise RuntimeError(f"source_range:{spec['cue_id']}")
            if summary.get("fusion_comp_count") != 1:
                raise RuntimeError(f"source_comp:{spec['cue_id']}")

        carrier_source = base.choose_carrier_source(
            source,
            max(spec["target_range"][1] - spec["target_range"][0] for spec in target_specs),
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
            "checked_at": base.utc_now(),
            "resolve_calls": resolve_calls,
            "open_page_call": open_page_call,
            "original_page": original_page,
            "before_timelines": before_timelines,
            "original_timeline_name": original_name,
            "source_timeline": {"name": SOURCE_TIMELINE_NAME, "unique_id": source_unique_id},
            "source_caption_count": len(source_caption_rows),
            "source_targets": source_before,
            "carrier_source": {
                key: base.json_safe(value)
                for key, value in carrier_source.items()
                if key not in {"item", "media_pool_item"}
            },
            "targets": target_specs,
            "accepted_state_sha256": accepted_hash,
        }
        base.write_json(report_dir / "probe_preflight.json", preflight)

        export_dir = report_dir / "source_comp_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        export_rows = []
        export_sources = [COME_SOURCE, THEY_STYLE_SOURCE]
        export_paths: Dict[str, Path] = {}
        for spec in export_sources:
            track, source_item = base.find_named_item(source, spec["name"])
            if source_item is None:
                raise RuntimeError(f"source_item:{spec['cue_id']}")
            comp_path = export_dir / f"{spec['cue_id']}.comp"
            value, row = base.direct_call(source_item, "ExportFusionComp", str(comp_path), 1)
            file_ok = bool(value and comp_path.is_file() and comp_path.stat().st_size > 0)
            export_paths[spec["cue_id"]] = comp_path
            export_rows.append({
                "cue_id": spec["cue_id"],
                "name": spec["name"],
                "track": track,
                "call": row,
                "path": str(comp_path),
                "size": comp_path.stat().st_size if comp_path.is_file() else 0,
                "sha256": base.raw_sha256(comp_path) if file_ok else None,
                "ok": file_ok,
            })
            if not file_ok:
                raise RuntimeError(f"source_comp_export:{spec['cue_id']}")
        base.write_json(report_dir / "source_comp_exports.json", {"rows": export_rows, "exported_count": len(export_rows), "ok": all(row["ok"] for row in export_rows)})

        value, duplicate_call = base.direct_call(source, "DuplicateTimeline", probe_name)
        duplicate = value if value is not None else base.find_timeline(project, probe_name)
        if duplicate is None:
            raise RuntimeError("duplicate_timeline")
        duplicate_created = True
        value, set_current_call = base.direct_call(project, "SetCurrentTimeline", duplicate)
        if not value:
            raise RuntimeError("select_duplicate")

        duplicate_before_captions = base.caption_items(duplicate)
        deletion = base.delete_items(duplicate, [item for _, item in duplicate_before_captions])
        time.sleep(0.20)
        remaining_captions = base.caption_items(duplicate)
        if not deletion.get("ok") or remaining_captions:
            raise RuntimeError(f"caption_cleanup:{len(remaining_captions)}")
        track_setup = base.ensure_video_tracks(duplicate, 5)
        if not track_setup.get("ok"):
            raise RuntimeError("video_tracks")
        base.write_json(report_dir / "duplicate_timeline_setup.json", {
            "duplicate_call": duplicate_call,
            "set_current_call": set_current_call,
            "duplicate_name": base.timeline_name(duplicate),
            "duplicate_unique_id": base.timeline_unique_id(duplicate),
            "caption_count_before_delete": len(duplicate_before_captions),
            "caption_delete": deletion,
            "caption_count_after_delete": len(remaining_captions),
            "track_setup": track_setup,
        })

        append = media.append_carriers_by_return_order(media_pool, duplicate, carrier_source, target_specs)
        base.write_json(report_dir / "carrier_append.json", base.json_safe({key: value for key, value in append.items() if key != "assigned"}))
        report["append_returned_count"] = append["returned_count"]
        report["append_detected_count"] = append["detected_count"]
        report["carrier_append_count"] = append["assigned_count"]
        if not append.get("ok"):
            raise RuntimeError("carrier_append_placement")

        assigned_by_name = {spec["name"]: item for spec, item in append["assigned"]}
        clone_rows = []
        for target_spec, source_cue_id in ((target_specs[0], "sub_052"), (target_specs[1], "sub_051")):
            target_item = assigned_by_name[target_spec["name"]]
            clone = media.import_source_comp(target_item, export_paths[source_cue_id])
            clone_rows.append({"target": target_spec, "source_cue_id": source_cue_id, "clone": clone, "ok": clone.get("ok") is True})
            if not clone.get("ok"):
                raise RuntimeError(f"media_fusion_import:{source_cue_id}")

        come_application = apply_come_correction(assigned_by_name[COME_SOURCE["name"]], come_plan)
        they_application = apply_they_correction(assigned_by_name[THEY_TARGET_NAME], they_plan)
        correction = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "clones": clone_rows,
            "come": come_application,
            "they": they_application,
            "ok": bool(come_application.get("ok") and they_application.get("ok")),
        }
        base.write_json(report_dir / "correction_application.json", correction)
        if not correction["ok"]:
            raise RuntimeError("visual_correction_application")

        first_save = base.save_project(project_manager)
        report["save_call_count"] += 1 if first_save.get("success") else 0
        if not first_save.get("success"):
            raise RuntimeError("save_probe")

        project_manager, project, media_pool, reacquire_calls = base.get_project(resolve)
        duplicate_after = base.find_timeline(project, probe_name)
        source_after = base.find_timeline(project, SOURCE_TIMELINE_NAME)
        if duplicate_after is None or source_after is None:
            raise RuntimeError("persistent_timeline_reacquire")

        come_track, come_item = base.find_named_item(duplicate_after, COME_SOURCE["name"])
        they_track, they_item = base.find_named_item(duplicate_after, THEY_TARGET_NAME)
        if come_item is None or they_item is None:
            raise RuntimeError("persistent_target_missing")
        come_summary = base.item_summary(int(come_track or 0), come_item)
        they_summary = base.item_summary(int(they_track or 0), they_item)
        come_visual = persistent_visual_readback(
            come_item,
            "COME",
            come_plan["center_keys"],
            come_plan["opacity_keys"],
            come_application["opacity"]["base_values"],
        )
        they_visual = persistent_visual_readback(
            they_item,
            "they",
            they_plan["position_keys"],
            they_plan["opacity_keys"],
            they_application["opacity"]["base_values"],
        )
        placement_ok = bool(media.placement_ok(come_summary, target_specs[0]) and media.placement_ok(they_summary, target_specs[1]))

        come_tool = base.get_text_tool(base.get_comp(come_item))
        they_tool = base.get_text_tool(base.get_comp(they_item))
        come_style = static_input_readback(come_tool, COME_SOURCE_FRAME_STYLE) if come_tool is not None else {"ok": False, "rows": []}
        they_stabilization = they_plan.get("stabilization") if isinstance(they_plan.get("stabilization"), dict) else {}
        they_shimmer_stabilized = bool(they_stabilization.get("ok"))
        come_at_433 = base.normalize_point(base.read_input(come_tool, "Center", 3)) if come_tool is not None else None
        they_at_433_key = next(row for row in they_plan["position_keys"] if row["timeline_frame"] == 433)
        they_at_433 = base.normalize_point(base.read_input(they_tool, "Center", int(they_at_433_key["local_frame"]))) if they_tool is not None else None
        relative_layout_ok = bool(
            come_at_433 is not None
            and they_at_433 is not None
            and they_at_433[1] > come_at_433[1] + 0.02
        )
        come_exit_start = base.normalize_point(base.read_input(come_tool, "Center", 17)) if come_tool is not None else None
        come_exit_end = base.normalize_point(base.read_input(come_tool, "Center", 21)) if come_tool is not None else None
        come_exit_opacity = base.read_input(come_tool, "Opacity1", 21) if come_tool is not None else None
        come_exit_ok = bool(
            come_exit_start is not None
            and come_exit_end is not None
            and come_exit_end[0] > come_exit_start[0] + 0.05
            and base.as_float(come_exit_opacity, 999.0) < 0.6
        )

        source_after_snapshot = source_identity(source_after, source_specs)
        source_protected = bool(
            base.timeline_unique_id(source_after) == source_unique_id
            and stable_source_identity(source_before) == stable_source_identity(source_after_snapshot)
        )
        accepted_unchanged = accepted_path.is_file() and base.raw_sha256(accepted_path) == accepted_hash
        targets_ok = bool(
            placement_ok
            and come_visual.get("ok")
            and they_visual.get("ok")
            and come_style.get("ok")
            and they_shimmer_stabilized
            and relative_layout_ok
            and come_exit_ok
        )
        persistent = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "checked_at": base.utc_now(),
            "reacquire_calls": reacquire_calls,
            "come": {"summary": come_summary, "visual": come_visual, "style": come_style},
            "they": {
                "summary": they_summary,
                "visual": they_visual,
                "stabilization": they_stabilization,
                "shimmer_stabilized": they_shimmer_stabilized,
            },
            "placement_ok": placement_ok,
            "relative_layout": {"come_at_433": come_at_433, "they_at_433": they_at_433, "they_above_come": relative_layout_ok},
            "come_exit": {"start": come_exit_start, "end": come_exit_end, "opacity1_end": base.json_safe(come_exit_opacity), "ok": come_exit_ok},
            "come_style_verified": come_style.get("ok") is True,
            "they_shimmer_stabilized": they_shimmer_stabilized,
            "targets_ok": targets_ok,
            "source_before": source_before,
            "source_after": source_after_snapshot,
            "source_timeline_unchanged": source_protected,
            "accepted_state_unchanged": accepted_unchanged,
            "probe_timeline_kept": True,
            "save": first_save,
        }
        base.write_json(report_dir / "persistent_readback.json", persistent)
        if not targets_ok:
            raise RuntimeError("persistent_target_readback")
        if not source_protected:
            raise RuntimeError("source_timeline_changed")
        if not accepted_unchanged:
            raise RuntimeError("accepted_state_changed")

        if original_page:
            opened, restore_page_call = base.direct_call(resolve, "OpenPage", original_page)
            report["restore_page_call"] = restore_page_call
            if not opened:
                raise RuntimeError("restore_page")

        report.update({
            "ok": True,
            "finished_at": base.utc_now(),
            "source_comp_export_count": len(export_rows),
            "comp_clone_count": len(clone_rows),
            "target_readback_count": 2,
            "visual_instance_source_cue_ids": they_plan["source_cue_ids"],
            "visual_instance_style_source_cue_id": they_plan["style_source_cue_id"],
            "visual_instance_window": they_plan["visual_window"],
            "relative_layout_verified": relative_layout_ok,
            "come_exit_verified": come_exit_ok,
            "come_style_verified": come_style.get("ok") is True,
            "they_shimmer_stabilized": they_shimmer_stabilized,
            "source_timeline_unchanged": source_protected,
            "accepted_state_unchanged": accepted_unchanged,
            "probe_timeline_kept": True,
            "probe_timeline_unique_id": base.timeline_unique_id(duplicate_after),
            "visual_review_required": True,
            "visual_review_window": [428, 452],
            "visual_review_instruction": (
                f"Open {probe_name} and review frames 428-452. The reconstructed lower-case they must remain "
                "stable above COME without shimmer. COME must match the baked dark-gray glyph size/style, then "
                "hold, roll right, and decay over frames 448-451."
            ),
        })
        base.write_json(report_dir / "probe_result.json", report)
        return report

    except BaseException as exc:
        report["failures"].append(base.compact_exception(exc))
        report["traceback"] = traceback.format_exc()
        cleanup = media.cleanup_probe(
            resolve,
            probe_name,
            original_name or SOURCE_TIMELINE_NAME,
            original_page,
            root,
            accepted_hash,
        ) if duplicate_created else {
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
            "probe_timeline_kept": False,
            "visual_review_required": False,
            "accepted_state_unchanged": cleanup.get("accepted_state_unchanged"),
        })
        base.write_json(report_dir / "probe_cleanup.json", cleanup)
        base.write_json(report_dir / "probe_result.json", report)
        return report
