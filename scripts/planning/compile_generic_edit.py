#!/usr/bin/env python3
"""
compile_generic_edit.py

Video Cloner generic edit compiler.

Purpose:
    Convert validated editor-agnostic edit_plan.json into a richer
    generic_edit_commands.json file that editor-specific compilers/controllers can
    execute without guessing.

Why this file matters:
    The planner decides intent. This compiler converts that intent into concrete,
    editor-neutral timing primitives:
        - source and timeline frame ranges
        - transform zoom keyframes
        - speed ramp segments
        - transition duration / placement / handle requirements
        - subtitle clips mapped from source transcript time to timeline time
        - resolved caption style payload
        - handle metadata for safer editor-specific translation

Compatibility:
    This keeps the old operation names and parameters used by the current Resolve
    controller, while adding richer fields for the next controller upgrades.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION = "generic_edit_compiler_v2_3_zoom_candidate_non_actionable"
DEFAULT_FPS = 24.0
DEFAULT_SUBTITLE_MIN_FRAMES = 6
DEFAULT_WORD_SUBTITLE_MIN_FRAMES = 3
DEFAULT_TRANSITION_MIN_FRAMES = 4
DEFAULT_TRANSITION_MAX_FRAMES = 18


# -------------------------
# IO
# -------------------------

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: Dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def get_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(round(float(value)))
    except Exception:
        return default


def clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(max_value, value))


def round4(value: Any) -> float:
    return round(get_float(value), 4)


def seconds_to_frame(seconds: Any, fps: float) -> int:
    return max(0, int(round(get_float(seconds) * fps)))


def frames_to_seconds(frames: Any, fps: float) -> float:
    fps = fps or DEFAULT_FPS
    return round(get_int(frames) / fps, 4)


# -------------------------
# Analysis helpers
# -------------------------

def get_analysis_shots(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Current pipeline shape.
    shots = analysis.get("timeline", {}).get("shots", [])
    if isinstance(shots, list):
        return shots

    # Defensive fallbacks for future merge_analysis versions.
    for key in ("shots", "scene_shots", "timeline_shots"):
        value = analysis.get(key)
        if isinstance(value, list):
            return value

    return []


def build_shot_index(analysis: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for shot in get_analysis_shots(analysis):
        shot_id = shot.get("shot_id")
        if shot_id is not None:
            out[int(shot_id)] = shot
    return out


def get_motion(shot: Dict[str, Any]) -> Dict[str, Any]:
    return shot.get("motion") or {}


def get_edit_signals(shot: Dict[str, Any]) -> Dict[str, Any]:
    return shot.get("edit_signals") or {}


def get_transition_to_next(shot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    transition = shot.get("transition_to_next")
    return transition if isinstance(transition, dict) else None


def get_action(plan_item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    actions = plan_item.get("actions") or []
    if not actions:
        return None
    action = actions[0]
    return action if isinstance(action, dict) else None


def get_source_fps(analysis: Dict[str, Any]) -> float:
    fps = get_float((analysis.get("job") or {}).get("fps"), 0.0)
    if fps > 0:
        return fps

    fps = get_float((analysis.get("source") or {}).get("fps"), 0.0)
    if fps > 0:
        return fps

    return DEFAULT_FPS


def get_source_frame_count(analysis: Dict[str, Any], fps: float) -> int:
    frame_count = get_int((analysis.get("job") or {}).get("frame_count"), 0)
    if frame_count > 0:
        return frame_count

    frame_count = get_int((analysis.get("source") or {}).get("frame_count"), 0)
    if frame_count > 0:
        return frame_count

    duration = get_float((analysis.get("summary") or {}).get("duration_seconds"), 0.0)
    if duration <= 0:
        duration = get_float((analysis.get("job") or {}).get("duration_seconds"), 0.0)

    return max(0, seconds_to_frame(duration, fps))


# -------------------------
# Source / timeline ranges
# -------------------------

def build_source_clip(shot: Dict[str, Any], fps: float) -> Dict[str, Any]:
    source_start = get_float(shot.get("start_seconds"), 0.0)
    source_end = get_float(shot.get("end_seconds"), source_start)
    duration = get_float(shot.get("duration_seconds"), max(0.0, source_end - source_start))

    start_frame = shot.get("start_frame")
    end_frame = shot.get("end_frame")

    if start_frame is None:
        start_frame = seconds_to_frame(source_start, fps)
    if end_frame is None:
        end_frame = seconds_to_frame(source_end, fps)

    start_frame_i = get_int(start_frame, 0)
    end_frame_i = max(start_frame_i + 1, get_int(end_frame, start_frame_i + 1))
    duration_frames = max(1, end_frame_i - start_frame_i)

    return {
        "shot_id": int(shot["shot_id"]),
        "source_start": round4(source_start),
        "source_end": round4(source_end),
        "duration": round4(duration),
        "duration_frames": duration_frames,
        "source_start_frame": start_frame_i,
        "source_end_frame": end_frame_i,
    }


def build_timeline_range(timeline_start_frame: int, duration_frames: int, fps: float) -> Dict[str, Any]:
    timeline_end_frame = timeline_start_frame + max(1, duration_frames)
    return {
        "timeline_start": frames_to_seconds(timeline_start_frame, fps),
        "timeline_end": frames_to_seconds(timeline_end_frame, fps),
        "timeline_duration": frames_to_seconds(duration_frames, fps),
        "timeline_start_frame": timeline_start_frame,
        "timeline_end_frame": timeline_end_frame,
        "timeline_duration_frames": max(1, duration_frames),
    }


def build_handles(source_clip: Dict[str, Any], source_frame_count: int, fps: float) -> Dict[str, Any]:
    source_start_frame = get_int(source_clip.get("source_start_frame"), 0)
    source_end_frame = get_int(source_clip.get("source_end_frame"), source_start_frame)
    pre_handle_frames = max(0, source_start_frame)
    post_handle_frames = max(0, source_frame_count - source_end_frame) if source_frame_count > 0 else 0

    return {
        "pre_handle_frames": pre_handle_frames,
        "post_handle_frames": post_handle_frames,
        "pre_handle_seconds": frames_to_seconds(pre_handle_frames, fps),
        "post_handle_seconds": frames_to_seconds(post_handle_frames, fps),
        "has_pre_handle": pre_handle_frames > 0,
        "has_post_handle": post_handle_frames > 0,
        "source_frame_count": source_frame_count,
    }


# -------------------------
# Operation compilers
# -------------------------

def speed_multiplier_from_action(action: Dict[str, Any]) -> float:
    hints = action.get("compiler_hints") or {}
    strength = hints.get("strength")

    if strength == "strong":
        return 1.45
    if strength == "medium":
        return 1.25
    if strength == "subtle":
        return 1.12
    return 1.2


def zoom_scale_from_action(action: Dict[str, Any]) -> float:
    hints = action.get("compiler_hints") or {}
    strength = hints.get("strength")

    if strength == "strong":
        return 1.18
    if strength == "medium":
        return 1.12
    return 1.06


def compile_hold(action: Dict[str, Any], shot: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "operation": "hold",
        "description": "Keep shot unchanged.",
        "parameters": {
            "preserve_duration": True,
            "preferred_timing": "full_shot",
        },
    }


def compile_cut(action: Dict[str, Any], shot: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    hints = action.get("compiler_hints") or {}
    return {
        "operation": "cut",
        "description": "Use shot as a normal timeline segment.",
        "parameters": {
            "sync_to_beat": bool(hints.get("sync_to_beat", False)),
            "preferred_timing": hints.get("preferred_timing", "shot_boundary"),
            "cut_policy": "use_compiled_timeline_range",
        },
    }


def compile_beat_cut(action: Dict[str, Any], shot: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    signals = get_edit_signals(shot)
    hints = action.get("compiler_hints") or {}
    nearest_start = signals.get("nearest_beat_to_start") or {}
    nearest_end = signals.get("nearest_beat_to_end") or {}

    fps = ctx["fps"]
    timeline_start_frame = ctx["timeline_start_frame"]

    nearest_start_time = nearest_start.get("time")
    nearest_end_time = nearest_end.get("time")

    return {
        "operation": "beat_cut",
        "description": "Align cut timing to nearby beat.",
        "parameters": {
            "sync_to_beat": True,
            "preferred_timing": "nearest_beat",
            "prefer_downbeat": bool(hints.get("prefer_downbeat", False)),
            "nearest_beat_to_start": nearest_start_time,
            "nearest_beat_to_end": nearest_end_time,
            "nearest_beat_to_start_frame": seconds_to_frame(nearest_start_time, fps) if nearest_start_time is not None else None,
            "nearest_beat_to_end_frame": seconds_to_frame(nearest_end_time, fps) if nearest_end_time is not None else None,
            "timeline_start_frame": timeline_start_frame,
        },
    }


def compile_zoom(action: Dict[str, Any], shot: Dict[str, Any], ctx: Dict[str, Any], direction: str) -> Dict[str, Any]:
    scale = zoom_scale_from_action(action)
    hints = action.get("compiler_hints") or {}
    timeline_start_frame = ctx["timeline_start_frame"]
    source_start_frame = ctx["source_clip"]["source_start_frame"]
    duration_frames = ctx["duration_frames"]
    last_frame = max(1, duration_frames - 1)

    if direction == "in":
        start_scale = 1.0
        end_scale = scale
    else:
        start_scale = scale
        end_scale = 1.0

    keyframes = [
        {
            "relative_frame": 0,
            "timeline_frame": timeline_start_frame,
            "source_frame": source_start_frame,
            "time": frames_to_seconds(timeline_start_frame, ctx["fps"]),
            "scale": round(start_scale, 4),
            "zoom": round(start_scale, 4),
        },
        {
            "relative_frame": last_frame,
            "timeline_frame": timeline_start_frame + last_frame,
            "source_frame": source_start_frame + last_frame,
            "time": frames_to_seconds(timeline_start_frame + last_frame, ctx["fps"]),
            "scale": round(end_scale, 4),
            "zoom": round(end_scale, 4),
        },
    ]

    return {
        "operation": "transform_zoom",
        "description": f"Apply editor-agnostic zoom {direction}.",
        "parameters": {
            "direction": direction,
            "start_scale": round(start_scale, 4),
            "end_scale": round(end_scale, 4),
            "easing": hints.get("easing", "ease_in_out"),
            "preferred_timing": hints.get("preferred_timing", "full_shot"),
            "duration_frames": duration_frames,
            "keyframes": keyframes,
        },
        "keyframes": keyframes,
    }


def build_speed_segments(multiplier: float, duration_frames: int, fps: float) -> List[Dict[str, Any]]:
    duration_frames = max(3, duration_frames)

    ramp_in_frames = max(1, int(round(duration_frames * 0.25)))
    ramp_out_frames = max(1, int(round(duration_frames * 0.25)))
    hold_frames = max(1, duration_frames - ramp_in_frames - ramp_out_frames)

    # Very short clips cannot hold a 25/50/25 split. Keep it valid.
    if ramp_in_frames + hold_frames + ramp_out_frames > duration_frames:
        hold_frames = max(1, duration_frames - ramp_in_frames - ramp_out_frames)
    if hold_frames <= 0:
        ramp_in_frames = max(1, duration_frames // 3)
        ramp_out_frames = max(1, duration_frames // 3)
        hold_frames = max(1, duration_frames - ramp_in_frames - ramp_out_frames)

    p0 = 0
    p1 = min(duration_frames, ramp_in_frames)
    p2 = min(duration_frames, p1 + hold_frames)
    p3 = duration_frames

    return [
        {
            "label": "ramp_in",
            "relative_start_frame": p0,
            "relative_end_frame": p1,
            "duration_frames": max(1, p1 - p0),
            "start_speed_multiplier": 1.0,
            "end_speed_multiplier": round(multiplier, 4),
            "curve": "ease_in",
            "duration_seconds": frames_to_seconds(max(1, p1 - p0), fps),
        },
        {
            "label": "hold_fast",
            "relative_start_frame": p1,
            "relative_end_frame": p2,
            "duration_frames": max(1, p2 - p1),
            "start_speed_multiplier": round(multiplier, 4),
            "end_speed_multiplier": round(multiplier, 4),
            "curve": "linear",
            "duration_seconds": frames_to_seconds(max(1, p2 - p1), fps),
        },
        {
            "label": "ramp_out",
            "relative_start_frame": p2,
            "relative_end_frame": p3,
            "duration_frames": max(1, p3 - p2),
            "start_speed_multiplier": round(multiplier, 4),
            "end_speed_multiplier": 1.0,
            "curve": "ease_out",
            "duration_seconds": frames_to_seconds(max(1, p3 - p2), fps),
        },
    ]


def compile_speed_ramp(action: Dict[str, Any], shot: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    multiplier = speed_multiplier_from_action(action)
    hints = action.get("compiler_hints") or {}
    duration_frames = ctx["duration_frames"]
    timeline_start_frame = ctx["timeline_start_frame"]
    source_start_frame = ctx["source_clip"]["source_start_frame"]
    segments = build_speed_segments(multiplier, duration_frames, ctx["fps"])

    for segment in segments:
        segment["timeline_start_frame"] = timeline_start_frame + segment["relative_start_frame"]
        segment["timeline_end_frame"] = timeline_start_frame + segment["relative_end_frame"]
        segment["source_start_frame"] = source_start_frame + segment["relative_start_frame"]
        segment["source_end_frame"] = source_start_frame + segment["relative_end_frame"]
        segment["speed_percent_start"] = round(segment["start_speed_multiplier"] * 100.0, 4)
        segment["speed_percent_end"] = round(segment["end_speed_multiplier"] * 100.0, 4)

    return {
        "operation": "speed_ramp",
        "description": "Apply smooth speed ramp inside the shot.",
        "parameters": {
            "style": hints.get("ramp_style", "smooth"),
            "speed_multiplier": round(multiplier, 4),
            "speed_percent": round(multiplier * 100.0, 4),
            "ramp_in_percent": 0.25,
            "hold_percent": 0.5,
            "ramp_out_percent": 0.25,
            "sync_to_beat": bool(hints.get("sync_to_beat", False)),
            "preferred_timing": hints.get("preferred_timing", "within_shot"),
            "duration_frames": duration_frames,
            "segments": segments,
        },
        "segments": segments,
    }


def compile_main_operation(action: Dict[str, Any], shot: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    action_type = action.get("type")

    if action_type == "hold":
        return compile_hold(action, shot, ctx)
    if action_type == "cut":
        return compile_cut(action, shot, ctx)
    if action_type == "beat_cut":
        return compile_beat_cut(action, shot, ctx)
    if action_type in {"zoom_in", "zoom_out"}:
        raise RuntimeError(
            "zoom action is not executable: current planner has no source-backed editable zoom authority contract"
        )
    if action_type == "speed_ramp":
        raise RuntimeError(
            "speed_ramp action is not executable: current planner has no source-backed retime authority contract"
        )

    return {
        "operation": "unknown",
        "description": "Unsupported action.",
        "parameters": {
            "action_type": action_type,
        },
    }


# -------------------------
# Transitions
# -------------------------

def transition_duration_frames(transition: Dict[str, Any], fps: float, current_duration_frames: int, next_duration_frames: int) -> int:
    strength = get_float(transition.get("transition_strength"), get_float(transition.get("strength"), 0.35))

    # Short-form friendly range: roughly 4-18 frames at 24fps.
    raw = int(round((0.12 + clamp(strength, 0.0, 1.0) * 0.32) * fps))
    raw = max(DEFAULT_TRANSITION_MIN_FRAMES, min(DEFAULT_TRANSITION_MAX_FRAMES, raw))

    # Do not consume too much of either side.
    max_by_clip = max(DEFAULT_TRANSITION_MIN_FRAMES, min(current_duration_frames, next_duration_frames) // 2)
    return max(DEFAULT_TRANSITION_MIN_FRAMES, min(raw, max_by_clip))


def compile_transition_hint(shot: Dict[str, Any], ctx: Dict[str, Any], next_ctx: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Creates safe generic transition hints only from analysis.json.
    Editor-specific compilers may ignore this or translate it to OTIO/FCPXML/Resolve.
    """
    transition = get_transition_to_next(shot)
    if not transition or not next_ctx:
        return None

    transition_type = transition.get("transition_type")
    confidence = transition.get("confidence")

    if confidence != "high":
        return None
    if not transition_type or "candidate" in str(transition_type).lower():
        return None

    fps = ctx["fps"]
    duration = transition_duration_frames(
        transition=transition,
        fps=fps,
        current_duration_frames=ctx["duration_frames"],
        next_duration_frames=next_ctx["duration_frames"],
    )

    outgoing_frames = duration // 2
    incoming_frames = duration - outgoing_frames
    cut_frame = ctx["timeline_end_frame"]

    current_handles = ctx.get("handles") or {}
    next_handles = next_ctx.get("handles") or {}

    handle_check = {
        "requires_handles": True,
        "required_outgoing_handle_frames": outgoing_frames,
        "required_incoming_handle_frames": incoming_frames,
        "available_outgoing_handle_frames": get_int(current_handles.get("post_handle_frames"), 0),
        "available_incoming_handle_frames": get_int(next_handles.get("pre_handle_frames"), 0),
    }
    handle_check["has_required_handles"] = (
        handle_check["available_outgoing_handle_frames"] >= outgoing_frames
        and handle_check["available_incoming_handle_frames"] >= incoming_frames
    )

    return {
        "operation": "transition_hint",
        "description": "High-confidence transition from analysis layer.",
        "parameters": {
            "transition_type": transition_type,
            "confidence": confidence,
            "strength": transition.get("transition_strength"),
            "cut_time": transition.get("cut_time"),
            "cut_frame": transition.get("cut_frame"),
            "timeline_cut_frame": cut_frame,
            "timeline_cut_seconds": frames_to_seconds(cut_frame, fps),
            "duration_frames": duration,
            "duration_seconds": frames_to_seconds(duration, fps),
            "side": "centered_on_cut",
            "placement": "between_current_and_next",
            "outgoing_frames": outgoing_frames,
            "incoming_frames": incoming_frames,
            "outgoing_command_id": ctx.get("command_id"),
            "incoming_shot_id": next_ctx.get("shot_id"),
            "handle_check": handle_check,
        },
    }


# -------------------------
# Caption style + subtitles
# -------------------------

def first_dict(*values: Any) -> Dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def clean_text(text: Any) -> str:
    return " ".join(str(text or "").replace("\n", " ").replace("\r", " ").split()).strip()


def count_text_words(text: Any) -> int:
    cleaned = clean_text(text)
    if not cleaned:
        return 0
    return len([part for part in cleaned.split(" ") if part.strip()])


def get_caption_plan(edit_plan: Dict[str, Any]) -> Dict[str, Any]:
    plan = edit_plan.get("caption_plan")
    return plan if isinstance(plan, dict) else {}


def find_caption_style_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return the raw caption-style detector payload when present.

    Note:
        analysis.caption_style_resolved is a resolved/fallback object.
        timeline.caption_style is the OCR detector payload with summary/groups.
        We return both through resolve_caption_style(), but keep this helper for
        backward compatibility with older merge_analysis outputs.
    """
    for key in ("caption_style", "captionStyle", "subtitle_style", "subtitles_style"):
        value = analysis.get(key)
        if isinstance(value, dict):
            return value

    timeline = analysis.get("timeline") or {}
    for key in ("caption_style", "captionStyle", "subtitle_style"):
        value = timeline.get(key)
        if isinstance(value, dict):
            return value

    layers = analysis.get("layers") or {}
    for key in ("caption_style", "subtitle_style"):
        value = layers.get(key)
        if isinstance(value, dict):
            return value

    return {}


def find_resolved_caption_style(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prefer explicit resolved caption style, but only trust it as detected when
    visible caption groups were actually found. Some detectors may emit a fallback
    object with available=true even when OCR found no subtitle groups.
    """
    candidates = [
        analysis.get("caption_style_resolved"),
        (analysis.get("timeline") or {}).get("caption_style_resolved"),
        ((analysis.get("sources") or {}).get("caption_style") or {}).get("resolved"),
    ]

    for candidate in candidates:
        if isinstance(candidate, dict) and candidate:
            return candidate

    return {}


def resolve_caption_style(analysis: Dict[str, Any], edit_plan: Dict[str, Any]) -> Dict[str, Any]:
    raw = find_caption_style_analysis(analysis)
    resolved = find_resolved_caption_style(analysis)
    global_style = edit_plan.get("global_style") or {}
    caption_plan = get_caption_plan(edit_plan)

    summary = first_dict(raw.get("summary"), raw.get("subtitle_style_summary"), raw.get("style_summary"))
    groups = raw.get("groups") or raw.get("subtitle_groups") or []

    has_visible = bool(summary.get("has_visible_captions"))
    groups_count = len(groups) if isinstance(groups, list) else get_int(summary.get("subtitle_groups_count"), 0)
    quality_label = ((summary.get("quality") or {}).get("label") if isinstance(summary.get("quality"), dict) else None)

    detected_is_reliable = bool(has_visible or groups_count > 0 or quality_label in {"low", "medium", "high"})

    plan_placement = caption_plan.get("placement")
    resolved_placement = resolved.get("placement")
    summary_placement = summary.get("placement") or summary.get("position")

    # If OCR found no captions, do not trust arbitrary resolved detector placement.
    if detected_is_reliable:
        placement = summary_placement or resolved_placement or plan_placement or "bottom_center"
        source = "analysis.caption_style.detected"
    else:
        placement = plan_placement or "bottom_center"
        source = "fallback.default_caption_style"

    resolved_text = resolved.get("text") if isinstance(resolved.get("text"), dict) else {}
    resolved_box = resolved.get("box") if isinstance(resolved.get("box"), dict) else {}
    resolved_animation = resolved.get("animation") if isinstance(resolved.get("animation"), dict) else {}

    style = {
        "enabled": True,
        "source": source,
        "detected_visible_captions": detected_is_reliable,
        "placement": placement,
        "safe_area": summary.get("safe_area") or resolved.get("safe_area") or "vertical_reels_safe_area",
        "font_family": (
            summary.get("font_family")
            or summary.get("font")
            or resolved_text.get("font_family")
            or global_style.get("font_family")
        ),
        "font_size": (
            summary.get("font_size")
            or summary.get("estimated_font_size")
            or resolved_text.get("font_size_px")
        ),
        "font_weight": summary.get("font_weight") or summary.get("weight") or resolved_text.get("font_weight"),
        "text_color": (
            summary.get("text_color")
            or summary.get("font_color")
            or resolved_text.get("fill_color")
            or "#ffffff"
        ),
        "stroke_color": (
            summary.get("stroke_color")
            or summary.get("outline_color")
            or resolved_text.get("stroke_color")
            or "#000000"
        ),
        "stroke_width": (
            summary.get("stroke_width")
            or summary.get("outline_width")
            or resolved_text.get("stroke_width_px")
            or 2
        ),
        "background": summary.get("background") or resolved_box,
        "case_style": summary.get("case_style") or summary.get("text_case") or resolved_text.get("case") or "preserve",
        "animation": summary.get("animation") or resolved_animation.get("style") or "none",
        "confidence": resolved.get("confidence") or quality_label or ("medium" if detected_is_reliable else "fallback"),
        "raw_summary": summary,
        "groups_count": groups_count,
    }

    return {k: v for k, v in style.items() if v is not None}


def find_transcript_data(analysis: Dict[str, Any]) -> Any:
    candidates = [
        analysis.get("transcript"),
        analysis.get("transcription"),
        analysis.get("speech"),
        (analysis.get("timeline") or {}).get("transcript"),
        (analysis.get("timeline") or {}).get("transcription"),
        (analysis.get("layers") or {}).get("transcript"),
        (analysis.get("audio") or {}).get("transcript"),
    ]

    for candidate in candidates:
        if candidate:
            return candidate

    return None


def extract_transcript_segments(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = find_transcript_data(analysis)
    if not data:
        return []

    if isinstance(data, list):
        segments = data
    elif isinstance(data, dict):
        segments = data.get("segments") or data.get("transcript_segments") or []
        if not segments and isinstance(data.get("result"), dict):
            segments = data["result"].get("segments") or []
    else:
        return []

    cleaned: List[Dict[str, Any]] = []
    for idx, seg in enumerate(segments):
        if not isinstance(seg, dict):
            continue
        text = clean_text(seg.get("text") or seg.get("caption") or "")
        start = get_float(seg.get("start"), get_float(seg.get("start_seconds"), -1.0))
        end = get_float(seg.get("end"), get_float(seg.get("end_seconds"), -1.0))
        if not text or start < 0 or end <= start:
            continue
        cleaned.append({
            "unit_id": seg.get("id") or f"segment_{idx + 1:04d}",
            "unit_type": "segment",
            "segment_index": idx,
            "text": text,
            "source_start": round4(start),
            "source_end": round4(end),
            "words": seg.get("words") if isinstance(seg.get("words"), list) else None,
            "source": "transcript_segments",
        })

    return cleaned


def extract_word_units_from_transcript(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    segments = extract_transcript_segments(analysis)
    out: List[Dict[str, Any]] = []

    for segment in segments:
        words = segment.get("words")
        if not isinstance(words, list):
            continue

        for word_index, word in enumerate(words):
            if not isinstance(word, dict):
                continue

            text = clean_text(word.get("text") or word.get("word") or "")
            start = get_float(word.get("start"), get_float(word.get("start_seconds"), -1.0))
            end = get_float(word.get("end"), get_float(word.get("end_seconds"), -1.0))
            if not text or start < 0:
                continue

            # Faster-Whisper can occasionally produce zero-length word timings.
            if end <= start:
                end = start + (DEFAULT_WORD_SUBTITLE_MIN_FRAMES / DEFAULT_FPS)

            out.append({
                "unit_id": f"word_{len(out) + 1:04d}",
                "unit_type": "word",
                "text": text,
                "source_start": round4(start),
                "source_end": round4(end),
                "segment_index": segment.get("segment_index"),
                "word_index": word_index,
                "probability": word.get("probability"),
                "source": "transcript_words",
            })

    return out


def candidate_locations(analysis: Dict[str, Any]) -> List[Any]:
    timeline = analysis.get("timeline") or {}
    transcript = find_transcript_data(analysis)
    locations: List[Any] = [
        timeline.get("subtitle_candidates"),
        analysis.get("subtitle_candidates"),
    ]

    if isinstance(transcript, dict):
        locations.extend([
            transcript.get("subtitle_candidates"),
            transcript.get("subtitle_clips"),
            transcript.get("captions"),
        ])

    locations.extend([
        timeline.get("subtitle_clips"),
        analysis.get("subtitle_clips"),
    ])

    return locations


def normalize_subtitle_candidate(candidate: Dict[str, Any], index: int) -> Optional[Dict[str, Any]]:
    text = clean_text(candidate.get("text") or candidate.get("caption") or candidate.get("word") or "")
    if not text:
        return None

    start = get_float(
        candidate.get("source_start"),
        get_float(
            candidate.get("start_seconds"),
            get_float(candidate.get("start"), -1.0),
        ),
    )
    end = get_float(
        candidate.get("source_end"),
        get_float(
            candidate.get("end_seconds"),
            get_float(candidate.get("end"), -1.0),
        ),
    )

    if start < 0 or end <= start:
        return None

    words_count = get_int(candidate.get("words_count"), count_text_words(text))
    unit_type = "word" if words_count <= 1 else "candidate"

    source_label = candidate.get("source") or "analysis_subtitle_candidates"
    if "word" in str(source_label).lower():
        unit_type = "word"

    return {
        "unit_id": candidate.get("subtitle_id") or candidate.get("id") or f"candidate_{index + 1:04d}",
        "unit_type": unit_type,
        "text": text,
        "source_start": round4(start),
        "source_end": round4(end),
        "shot_id": candidate.get("shot_id"),
        "words_count": words_count,
        "words": candidate.get("words") if isinstance(candidate.get("words"), list) else None,
        "source": source_label,
    }


def extract_subtitle_candidates(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    for location in candidate_locations(analysis):
        if not isinstance(location, list) or not location:
            continue

        out: List[Dict[str, Any]] = []
        for idx, candidate in enumerate(location):
            if not isinstance(candidate, dict):
                continue
            normalized = normalize_subtitle_candidate(candidate, idx)
            if normalized:
                out.append(normalized)

        if out:
            return sorted(out, key=lambda x: (get_float(x.get("source_start"), 0.0), get_float(x.get("source_end"), 0.0)))

    return []


def subtitle_units_look_word_level(units: List[Dict[str, Any]]) -> bool:
    if not units:
        return False

    word_like = 0
    for unit in units:
        if unit.get("unit_type") == "word":
            word_like += 1
            continue
        if get_int(unit.get("words_count"), count_text_words(unit.get("text"))) <= 1:
            word_like += 1

    return (word_like / max(1, len(units))) >= 0.80


def choose_subtitle_units(
    analysis: Dict[str, Any],
    edit_plan: Dict[str, Any],
    subtitle_source: str = "auto",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Selection order:
        - explicit candidates: use analysis.timeline.subtitle_candidates
        - explicit words: split transcript words into one subtitle per word
        - explicit segments: use transcript segments
        - auto:
            1) if subtitle_candidates are word-level, use them
            2) if caption plan requests high density and word timestamps exist, use words
            3) if candidates exist, use candidates
            4) otherwise fallback to segments

    This fixes the earlier bug where generic_edit_commands always fell back to
    transcript segments and ignored caption-ready candidates/word timings.
    """
    subtitle_source = str(subtitle_source or "auto").lower()

    candidates = extract_subtitle_candidates(analysis)
    word_units = extract_word_units_from_transcript(analysis)
    segment_units = extract_transcript_segments(analysis)
    caption_plan = get_caption_plan(edit_plan)
    density = str(caption_plan.get("density") or "").lower()

    selected_source = "none"
    units: List[Dict[str, Any]] = []

    if subtitle_source == "candidates":
        units = candidates
        selected_source = "analysis_subtitle_candidates"
    elif subtitle_source == "words":
        units = word_units
        selected_source = "transcript_words"
    elif subtitle_source == "segments":
        units = segment_units
        selected_source = "transcript_segments"
    else:
        if candidates and subtitle_units_look_word_level(candidates):
            units = candidates
            selected_source = "analysis_subtitle_candidates_word_level"
        elif word_units and density in {"high", "word", "word_by_word", "one_word", "one_word_at_a_time"}:
            units = word_units
            selected_source = "transcript_words_auto_high_density"
        elif candidates:
            units = candidates
            selected_source = "analysis_subtitle_candidates"
        elif word_units and not segment_units:
            units = word_units
            selected_source = "transcript_words_auto_no_segments"
        else:
            units = segment_units
            selected_source = "transcript_segments_fallback"

    meta = {
        "subtitle_source_requested": subtitle_source,
        "subtitle_source_selected": selected_source,
        "candidates_count": len(candidates),
        "candidate_units_word_level": subtitle_units_look_word_level(candidates),
        "transcript_word_units_count": len(word_units),
        "transcript_segment_units_count": len(segment_units),
        "caption_plan_density": density or None,
        "word_level_output": bool(units and subtitle_units_look_word_level(units)),
    }

    return units, meta


def source_time_to_timeline_frame(
    source_time: float,
    commands: List[Dict[str, Any]],
    fps: float,
    prefer_next_at_boundary: bool = False,
) -> Optional[int]:
    epsilon = max(0.001, 0.25 / max(fps, 1.0))

    if prefer_next_at_boundary:
        for cmd in commands:
            source_start = get_float(cmd.get("source_start"), 0.0)
            if abs(source_time - source_start) <= epsilon:
                return get_int(cmd.get("timeline_start_frame"), 0)

    for cmd in commands:
        source_start = get_float(cmd.get("source_start"), 0.0)
        source_end = get_float(cmd.get("source_end"), 0.0)
        if source_start <= source_time < source_end:
            rel_seconds = max(0.0, source_time - source_start)
            return get_int(cmd.get("timeline_start_frame"), 0) + seconds_to_frame(rel_seconds, fps)

    # End-boundary fallback, mostly for subtitle end times exactly on a cut.
    for cmd in reversed(commands):
        source_start = get_float(cmd.get("source_start"), 0.0)
        source_end = get_float(cmd.get("source_end"), 0.0)
        if source_start <= source_time <= source_end + epsilon:
            rel_seconds = max(0.0, min(source_time, source_end) - source_start)
            return get_int(cmd.get("timeline_start_frame"), 0) + seconds_to_frame(rel_seconds, fps)

    return None


def build_subtitle_clips(
    analysis: Dict[str, Any],
    edit_plan: Dict[str, Any],
    commands: List[Dict[str, Any]],
    caption_style_resolved: Dict[str, Any],
    fps: float,
    subtitle_source: str = "auto",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    units, meta = choose_subtitle_units(
        analysis=analysis,
        edit_plan=edit_plan,
        subtitle_source=subtitle_source,
    )

    if not units or not commands:
        meta.update({
            "subtitle_clips_count": 0,
            "reason": "no subtitle units or no commands",
        })
        return [], meta

    subtitle_clips: List[Dict[str, Any]] = []
    skipped = 0

    for i, unit in enumerate(units, start=1):
        start_frame = source_time_to_timeline_frame(
            unit["source_start"],
            commands,
            fps,
            prefer_next_at_boundary=True,
        )
        end_frame = source_time_to_timeline_frame(
            unit["source_end"],
            commands,
            fps,
            prefer_next_at_boundary=False,
        )

        if start_frame is None or end_frame is None:
            skipped += 1
            continue

        min_frames = DEFAULT_WORD_SUBTITLE_MIN_FRAMES if unit.get("unit_type") == "word" else DEFAULT_SUBTITLE_MIN_FRAMES
        if end_frame <= start_frame:
            end_frame = start_frame + min_frames

        duration_frames = max(min_frames, end_frame - start_frame)
        end_frame = start_frame + duration_frames

        subtitle_clips.append({
            "subtitle_id": f"sub_{len(subtitle_clips) + 1:03d}",
            "source_unit_id": unit.get("unit_id"),
            "unit_type": unit.get("unit_type"),
            "text": unit["text"],
            "source_start": unit["source_start"],
            "source_end": unit["source_end"],
            "timeline_start": frames_to_seconds(start_frame, fps),
            "timeline_end": frames_to_seconds(end_frame, fps),
            "timeline_start_frame": start_frame,
            "timeline_end_frame": end_frame,
            "duration_frames": duration_frames,
            "duration_seconds": frames_to_seconds(duration_frames, fps),
            "style_ref": "caption_style_resolved",
            "placement": caption_style_resolved.get("placement", "bottom_center"),
            "words": unit.get("words"),
            "word_index": unit.get("word_index"),
            "segment_index": unit.get("segment_index"),
            "probability": unit.get("probability"),
            "source": unit.get("source"),
        })

    meta.update({
        "subtitle_units_count": len(units),
        "subtitle_clips_count": len(subtitle_clips),
        "skipped_units_count": skipped,
        "first_clip_text": subtitle_clips[0]["text"] if subtitle_clips else None,
        "average_words_per_clip": round(
            sum(count_text_words(c.get("text")) for c in subtitle_clips) / max(1, len(subtitle_clips)),
            4,
        ) if subtitle_clips else 0,
    })

    return subtitle_clips, meta


# -------------------------
# Timeline compilation
# -------------------------

def precompute_contexts(timeline_items: List[Dict[str, Any]], shot_index: Dict[int, Dict[str, Any]], analysis: Dict[str, Any], fps: float) -> Dict[int, Dict[str, Any]]:
    source_frame_count = get_source_frame_count(analysis, fps)
    contexts: Dict[int, Dict[str, Any]] = {}
    timeline_cursor = 0

    for item in timeline_items:
        try:
            shot_id = int(item["shot_id"])
        except Exception:
            continue

        source_shot = shot_index.get(shot_id)
        if not source_shot:
            continue

        source_clip = build_source_clip(source_shot, fps)
        duration_frames = get_int(source_clip.get("duration_frames"), 1)
        timeline_range = build_timeline_range(timeline_cursor, duration_frames, fps)
        handles = build_handles(source_clip, source_frame_count, fps)

        contexts[shot_id] = {
            "shot_id": shot_id,
            "source_shot": source_shot,
            "source_clip": source_clip,
            "duration_frames": duration_frames,
            "fps": fps,
            "handles": handles,
            **timeline_range,
        }
        timeline_cursor += duration_frames

    return contexts


def compile_timeline(validated_plan: Dict[str, Any], analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    edit_plan = validated_plan.get("edit_plan", validated_plan)
    shot_index = build_shot_index(analysis)
    fps = get_source_fps(analysis)

    commands: List[Dict[str, Any]] = []
    timeline_items = edit_plan.get("timeline", [])
    contexts = precompute_contexts(timeline_items, shot_index, analysis, fps)

    for idx, item in enumerate(timeline_items):
        try:
            shot_id = int(item["shot_id"])
        except Exception:
            continue

        ctx = contexts.get(shot_id)
        if not ctx:
            continue

        source_shot = ctx["source_shot"]
        action = get_action(item)
        if not action:
            continue

        source_clip = ctx["source_clip"]
        source_start = source_clip["source_start"]
        source_end = source_clip["source_end"]
        duration = source_clip["duration"]

        command_id = f"cmd_{shot_id:03d}"
        ctx["command_id"] = command_id

        main_operation = compile_main_operation(action, source_shot, ctx)

        next_ctx = None
        for next_item in timeline_items[idx + 1:]:
            next_shot_id = next_item.get("shot_id")
            if next_shot_id is not None and int(next_shot_id) in contexts:
                next_ctx = contexts[int(next_shot_id)]
                break

        transition_hint = compile_transition_hint(source_shot, ctx, next_ctx)
        operations = [main_operation]
        if transition_hint:
            operations.append(transition_hint)

        compiled_item = {
            "command_id": command_id,
            "shot_id": shot_id,

            # SOURCE OF TRUTH: source ranges.
            "source_start": round(source_start, 4),
            "source_end": round(source_end, 4),
            "source_duration": round(duration, 4),
            "source_start_frame": source_clip["source_start_frame"],
            "source_end_frame": source_clip["source_end_frame"],
            "source_duration_frames": source_clip["duration_frames"],

            # New: compiled timeline ranges.
            "timeline_start": ctx["timeline_start"],
            "timeline_end": ctx["timeline_end"],
            "timeline_duration": ctx["timeline_duration"],
            "timeline_start_frame": ctx["timeline_start_frame"],
            "timeline_end_frame": ctx["timeline_end_frame"],
            "timeline_duration_frames": ctx["timeline_duration_frames"],

            # Existing nested source_clip kept for compatibility.
            "source_clip": source_clip,

            # New: handle metadata for transition/speed/trim decisions.
            "handles": ctx["handles"],

            "action": {
                "type": action.get("type"),
                "rule_id": action.get("rule_id"),
                "confidence": action.get("confidence"),
                "priority_score": action.get("priority_score"),
                "intent": action.get("intent"),
                "reason": action.get("reason"),
            },
            "observations": item.get("observations") or {},

            "operations": operations,
            "compiler_hints": action.get("compiler_hints") or {},
        }

        commands.append(compiled_item)

    return commands


def build_summary(commands: List[Dict[str, Any]], subtitle_clips: List[Dict[str, Any]], subtitle_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    operation_counts: Dict[str, int] = {}
    transition_handle_warnings = 0

    for cmd in commands:
        for op in cmd.get("operations", []):
            name = op.get("operation")
            operation_counts[name] = operation_counts.get(name, 0) + 1
            if name == "transition_hint":
                params = op.get("parameters") or {}
                handle_check = params.get("handle_check") or {}
                if handle_check and not handle_check.get("has_required_handles", False):
                    transition_handle_warnings += 1

    timeline_duration_frames = commands[-1]["timeline_end_frame"] if commands else 0
    fps = DEFAULT_FPS
    if commands:
        timeline_duration = get_float(commands[-1].get("timeline_end"), 0.0)
        if timeline_duration > 0 and timeline_duration_frames > 0:
            fps = timeline_duration_frames / timeline_duration

    return {
        "commands_count": len(commands),
        "operation_counts": operation_counts,
        "source_duration": round(commands[-1]["source_end"], 4) if commands else 0.0,
        "timeline_duration": frames_to_seconds(timeline_duration_frames, fps),
        "timeline_duration_frames": timeline_duration_frames,
        "subtitle_clips_count": len(subtitle_clips),
        "subtitle_source_selected": (subtitle_meta or {}).get("subtitle_source_selected"),
        "word_level_subtitles": bool((subtitle_meta or {}).get("word_level_output", False)),
        "average_words_per_subtitle": (subtitle_meta or {}).get("average_words_per_clip"),
        "transition_handle_warnings": transition_handle_warnings,
    }


def compile_generic(validated_plan: Dict[str, Any], analysis: Dict[str, Any], include_subtitles: bool = True, subtitle_source: str = "auto") -> Dict[str, Any]:
    commands = compile_timeline(validated_plan, analysis)
    edit_plan = validated_plan.get("edit_plan", validated_plan)
    fps = get_source_fps(analysis)
    caption_style_resolved = resolve_caption_style(analysis, edit_plan)
    subtitle_clips, subtitle_meta = build_subtitle_clips(
        analysis=analysis,
        edit_plan=edit_plan,
        commands=commands,
        caption_style_resolved=caption_style_resolved,
        fps=fps,
        subtitle_source=subtitle_source,
    ) if include_subtitles else ([], {"subtitle_source_requested": subtitle_source, "subtitle_source_selected": "disabled", "subtitle_clips_count": 0})

    output = {
        "success": True,
        "compiler_version": VERSION,
        "schema": "generic_edit_commands",
        "schema_version": "2.0",
        "video_id": edit_plan.get("video_id"),
        "source": {
            "analysis_video_id": analysis.get("job", {}).get("job_id"),
            "source_video": analysis.get("job", {}).get("source_video"),
            "source_audio": analysis.get("job", {}).get("source_audio"),
            "duration_seconds": analysis.get("summary", {}).get("duration_seconds"),
            "fps": fps,
            "frame_count": get_source_frame_count(analysis, fps),
        },
        "global_style": edit_plan.get("global_style", {}),
        "caption_style_resolved": caption_style_resolved,
        "subtitle_clips": subtitle_clips,
        "subtitle_generation": subtitle_meta,
        "summary": build_summary(commands, subtitle_clips, subtitle_meta),
        "timeline": commands,
        "_meta": {
            "created_at_unix": round(time.time(), 3),
            "editor_agnostic": True,
            "transitions_added_from_analysis": True,
            "rich_execution_contract": True,
            "ready_for_editor_specific_compilers": True,
            "new_contract_fields": [
                "timeline_start_frame",
                "timeline_end_frame",
                "source_start_frame",
                "source_end_frame",
                "handles",
                "transform_zoom.parameters.keyframes",
                "observations.speed_ramp_candidate",
                "transition_hint.parameters.duration_frames",
                "transition_hint.parameters.side",
                "transition_hint.parameters.placement",
                "subtitle_clips",
                "subtitle_generation",
                "caption_style_resolved",
            ],
            "target_compilers": [
                "OpenReel",
                "DaVinci Resolve",
                "CapCut or other future adapters",
            ],
        },
    }

    return output


# -------------------------
# CLI
# -------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile validated editor-agnostic edit plan into rich generic edit commands."
    )

    parser.add_argument("--analysis", required=True, help="Path to analysis.json")
    parser.add_argument("--validated-edit-plan", required=True, help="Path to validated_edit_plan.json")
    parser.add_argument("--output", required=True, help="Path to generic_edit_commands.json")
    parser.add_argument(
        "--no-subtitles",
        action="store_true",
        help="Do not emit subtitle_clips even if transcript data is available in analysis.json.",
    )
    parser.add_argument(
        "--subtitle-source",
        choices=["auto", "candidates", "words", "segments"],
        default="auto",
        help=(
            "Subtitle source strategy. auto prefers word-level subtitle_candidates, "
            "then transcript words when caption_plan.density is high, then candidates, then segments."
        ),
    )

    args = parser.parse_args()

    analysis = load_json(args.analysis)
    validated_plan = load_json(args.validated_edit_plan)

    if not validated_plan.get("success", False):
        raise RuntimeError("validated_edit_plan.success is not true. Refusing to compile invalid plan.")

    compiled = compile_generic(
        validated_plan=validated_plan,
        analysis=analysis,
        include_subtitles=not args.no_subtitles,
        subtitle_source=args.subtitle_source,
    )
    save_json(args.output, compiled)

    print(json.dumps({
        "ok": True,
        "compiler_version": VERSION,
        "schema_version": compiled.get("schema_version"),
        "output": os.path.abspath(args.output),
        "video_id": compiled.get("video_id"),
        "commands_count": compiled["summary"]["commands_count"],
        "operation_counts": compiled["summary"]["operation_counts"],
        "subtitle_clips_count": compiled["summary"].get("subtitle_clips_count", 0),
        "subtitle_source_selected": compiled["summary"].get("subtitle_source_selected"),
        "word_level_subtitles": compiled["summary"].get("word_level_subtitles"),
        "average_words_per_subtitle": compiled["summary"].get("average_words_per_subtitle"),
        "timeline_duration_frames": compiled["summary"].get("timeline_duration_frames", 0),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
