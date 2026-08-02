#!/usr/bin/env python3
"""
compile_davinci_otio.py

DaVinci Resolve OTIO compiler for the Video Cloner pipeline.

Purpose:
    Convert generic_edit_commands.json into an OTIO timeline that Resolve can import.

Architecture:
    - This file creates the base editable timeline: ordered video clips + optional audio.
    - It preserves rich Video Cloner metadata and markers.
    - It does NOT try to bake animated zooms, real speed ramps, or complex subtitles.
      Those are applied later by resolve_apply_video_cloner_metadata.py or future
      editor-specific controllers.

Why:
    Resolve's OTIO import is good for clip structure and basic metadata, but unreliable
    for complex keyframes. The controller is the safer place for animated transforms.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import opentimelineio as otio
except Exception as exc:
    print(json.dumps({
        "ok": False,
        "error": "OpenTimelineIO is not installed or cannot be imported.",
        "details": str(exc),
        "fix": "pip install opentimelineio"
    }, indent=2), flush=True)
    sys.exit(1)


VERSION = "davinci_otio_compiler_v2_3_rich_metadata_markers"


# -----------------------------
# IO / basic helpers
# -----------------------------

def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


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


def get_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def safe_name(value: Any, max_len: int = 80) -> str:
    value = str(value or "").strip()
    if not value:
        return "Untitled"
    cleaned = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_len] if cleaned else "Untitled"


def slug(value: Any, max_len: int = 48) -> str:
    value = str(value or "unknown").strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return (value or "unknown")[:max_len]


def path_to_resolve_media_target(path: Optional[str], mode: str = "resolve_unescaped_file_uri") -> Optional[str]:
    """
    Convert a local media path to a target_url for OTIO.

    Resolve can parse official OTIO but sometimes fails to auto-link media when
    target_url contains percent-encoded spaces, for example Video%20Cloner.

    Modes:
    - resolve_unescaped_file_uri: file:///C:/path with normal spaces.
    - file_uri: pathlib.as_uri(), standards-compliant URI with %20.
    - native: native OS absolute path.
    - posix: absolute path with forward slashes.
    - basename: only filename. Useful when testing Resolve folder relink.
    """
    if not path:
        return None

    p = Path(path).expanduser().resolve()
    mode = str(mode or "resolve_unescaped_file_uri").strip().lower()

    if mode == "file_uri":
        return p.as_uri()

    if mode == "native":
        return str(p)

    if mode == "posix":
        return p.as_posix()

    if mode == "basename":
        return p.name

    if mode == "resolve_unescaped_file_uri":
        return "file:///" + p.as_posix()

    raise ValueError(f"Unsupported media URL mode: {mode}")


# -----------------------------
# OTIO time helpers
# -----------------------------

def rt(value: float, rate: float) -> otio.opentime.RationalTime:
    return otio.opentime.RationalTime(float(value), float(rate))


def tr(start_value: float, duration_value: float, rate: float) -> otio.opentime.TimeRange:
    return otio.opentime.TimeRange(
        start_time=rt(start_value, rate),
        duration=rt(max(1, duration_value), rate),
    )


def frames_to_seconds(frames: int, fps: float) -> float:
    return round(float(frames) / float(fps), 6) if fps else 0.0


def seconds_to_frames(seconds: Any, fps: float, default: int = 0) -> int:
    return get_int(get_float(seconds, 0.0) * fps, default)


# -----------------------------
# Generic command helpers
# -----------------------------

def get_fps(generic_commands: Dict[str, Any]) -> float:
    source = generic_commands.get("source") or {}
    fps = get_float(source.get("fps"), 24.0)
    return fps if fps > 0 else 24.0


def get_frame_count(generic_commands: Dict[str, Any], fps: float) -> int:
    source = generic_commands.get("source") or {}

    frame_count = get_int(source.get("frame_count"), 0)
    if frame_count > 0:
        return frame_count

    duration_seconds = get_float(source.get("duration_seconds"), 0.0)
    if duration_seconds > 0:
        return max(1, int(round(duration_seconds * fps)))

    timeline = generic_commands.get("timeline") or []
    max_end = 0
    for cmd in timeline:
        source_clip = cmd.get("source_clip") or {}
        max_end = max(
            max_end,
            get_int(source_clip.get("source_end_frame"), 0),
            get_int(cmd.get("source_end_frame"), 0),
            seconds_to_frames(cmd.get("source_end"), fps, 0),
        )
    return max(1, max_end)


def get_source_video(generic_commands: Dict[str, Any]) -> Optional[str]:
    return (generic_commands.get("source") or {}).get("source_video")


def get_source_audio(generic_commands: Dict[str, Any]) -> Optional[str]:
    return (generic_commands.get("source") or {}).get("source_audio")


def get_operations(cmd: Dict[str, Any]) -> List[Dict[str, Any]]:
    ops = cmd.get("operations")
    return ops if isinstance(ops, list) else []


def find_operation(cmd: Dict[str, Any], operation_name: str) -> Optional[Dict[str, Any]]:
    for op in get_operations(cmd):
        if op.get("operation") == operation_name:
            return op
    return None


def source_range_from_command(cmd: Dict[str, Any], fps: float) -> Tuple[int, int]:
    """
    Return (source_start_frame, duration_frames).

    Prefer rich v2 command fields, then source_clip fields, then seconds.
    """
    source_clip = cmd.get("source_clip") or {}

    start_frame = (
        cmd.get("source_start_frame")
        if cmd.get("source_start_frame") is not None
        else source_clip.get("source_start_frame")
    )
    end_frame = (
        cmd.get("source_end_frame")
        if cmd.get("source_end_frame") is not None
        else source_clip.get("source_end_frame")
    )

    if start_frame is not None and end_frame is not None:
        start_frame = get_int(start_frame)
        end_frame = get_int(end_frame)
        return start_frame, max(1, end_frame - start_frame)

    source_start = get_float(
        source_clip.get("source_start"),
        get_float(cmd.get("source_start"), 0.0),
    )

    duration_seconds = get_float(
        source_clip.get("duration"),
        get_float(cmd.get("source_duration"), get_float(cmd.get("timeline_duration"), 0.0)),
    )

    return int(round(source_start * fps)), max(1, int(round(duration_seconds * fps)))


def timeline_range_from_command(cmd: Dict[str, Any], fallback_start_frame: int, fps: float) -> Tuple[int, int]:
    """
    Return (timeline_start_frame, duration_frames).
    Falls back to sequential timeline position if compiler v1 data lacks timeline fields.
    """
    start = cmd.get("timeline_start_frame")
    end = cmd.get("timeline_end_frame")

    if start is not None and end is not None:
        start_i = get_int(start)
        end_i = get_int(end)
        return start_i, max(1, end_i - start_i)

    timeline_start = cmd.get("timeline_start")
    timeline_duration = cmd.get("timeline_duration")
    if timeline_start is not None and timeline_duration is not None:
        start_i = int(round(get_float(timeline_start, 0.0) * fps))
        duration_i = max(1, int(round(get_float(timeline_duration, 0.0) * fps)))
        return start_i, duration_i

    _, duration_frames = source_range_from_command(cmd, fps)
    return fallback_start_frame, duration_frames


def operation_counts(generic_commands: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for cmd in generic_commands.get("timeline") or []:
        for op in get_operations(cmd):
            name = str(op.get("operation") or "unknown")
            counts[name] = counts.get(name, 0) + 1
    return counts


def get_action_type(cmd: Dict[str, Any]) -> str:
    return str((cmd.get("action") or {}).get("type") or "unknown")


def get_command_index(cmd: Dict[str, Any], fallback_index: int = 0) -> int:
    command_id = str(cmd.get("command_id") or "")
    match = re.search(r"(\d+)$", command_id)
    if match:
        return get_int(match.group(1), fallback_index)
    return fallback_index


# -----------------------------
# Marker helpers
# -----------------------------

def marker_color(name: str) -> otio.schema.MarkerColor:
    colors = {
        "BLUE": otio.schema.MarkerColor.BLUE,
        "GREEN": otio.schema.MarkerColor.GREEN,
        "PURPLE": otio.schema.MarkerColor.PURPLE,
        "RED": otio.schema.MarkerColor.RED,
        "YELLOW": otio.schema.MarkerColor.YELLOW,
        "CYAN": otio.schema.MarkerColor.CYAN,
        "MAGENTA": otio.schema.MarkerColor.MAGENTA,
        "ORANGE": otio.schema.MarkerColor.ORANGE,
    }
    return colors.get(str(name).upper(), otio.schema.MarkerColor.BLUE)


def make_marker(name: str, start_frame: int, duration_frames: int, fps: float, color: str = "BLUE", metadata: Optional[Dict[str, Any]] = None) -> otio.schema.Marker:
    return otio.schema.Marker(
        name=safe_name(name, 96),
        marked_range=tr(start_frame, max(1, duration_frames), fps),
        color=marker_color(color),
        metadata=metadata or {},
    )


def vc_marker_metadata(
    marker_type: str,
    cmd: Optional[Dict[str, Any]] = None,
    op: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema": "video_cloner_otio_marker",
        "compiler_version": VERSION,
        "marker_type": marker_type,
    }

    if cmd:
        payload.update({
            "command_id": cmd.get("command_id"),
            "shot_id": cmd.get("shot_id"),
            "action_type": get_action_type(cmd),
        })

    if op:
        payload["operation"] = op

    if extra:
        payload.update(extra)

    return {"video_cloner": payload}


def marker_start_local_from_relative(relative_frame: Any, duration_frames: int) -> int:
    frame = get_int(relative_frame, 0)
    return max(0, min(frame, max(0, duration_frames - 1)))


def add_clip_marker_if_enabled(
    clip: otio.schema.Clip,
    include_markers: bool,
    name: str,
    start_frame: int,
    duration_frames: int,
    fps: float,
    color: str,
    metadata: Dict[str, Any],
) -> None:
    if include_markers:
        clip.markers.append(make_marker(name, start_frame, duration_frames, fps, color, metadata))


def add_track_marker_if_enabled(
    track: otio.schema.Track,
    include_markers: bool,
    name: str,
    timeline_start_frame: int,
    duration_frames: int,
    fps: float,
    color: str,
    metadata: Dict[str, Any],
) -> None:
    if include_markers:
        track.markers.append(make_marker(name, timeline_start_frame, duration_frames, fps, color, metadata))


# -----------------------------
# Rich metadata
# -----------------------------

def build_clip_metadata(cmd: Dict[str, Any], timeline_start_frame: int, duration_frames: int, fps: float) -> Dict[str, Any]:
    action = cmd.get("action") or {}
    source_clip = cmd.get("source_clip") or {}
    source_start_frame, source_duration_frames = source_range_from_command(cmd, fps)

    timeline_payload = {
        "timeline_start_frame": timeline_start_frame,
        "timeline_end_frame": timeline_start_frame + duration_frames,
        "timeline_duration_frames": duration_frames,
        "timeline_start_seconds": frames_to_seconds(timeline_start_frame, fps),
        "timeline_end_seconds": frames_to_seconds(timeline_start_frame + duration_frames, fps),
        "timeline_duration_seconds": frames_to_seconds(duration_frames, fps),
    }

    source_payload = {
        "source_start_frame": source_start_frame,
        "source_end_frame": source_start_frame + source_duration_frames,
        "source_duration_frames": source_duration_frames,
        "source_start_seconds": frames_to_seconds(source_start_frame, fps),
        "source_end_seconds": frames_to_seconds(source_start_frame + source_duration_frames, fps),
        "source_duration_seconds": frames_to_seconds(source_duration_frames, fps),
    }

    return {
        "video_cloner": {
            "schema": "generic_to_davinci_otio_metadata",
            "schema_version": "2.3",
            "compiler_version": VERSION,
            "command_id": cmd.get("command_id"),
            "shot_id": cmd.get("shot_id"),
            "action": action,
            "action_type": action.get("type"),
            "operations": get_operations(cmd),
            "operation_names": [op.get("operation") for op in get_operations(cmd)],
            "compiler_hints": cmd.get("compiler_hints") or {},
            "source_clip": source_clip,
            "source_range": source_payload,
            "timeline_range": timeline_payload,
            "handles": cmd.get("handles") or {},
            "caption_style_resolved": cmd.get("caption_style_resolved"),
            "controller_contract": {
                "animated_zoom": "resolve_apply_video_cloner_metadata.py",
                "speed_ramps": "controller_or_future_xml_strategy",
                "transitions": "markers_and_optional_basic_otio_transition",
                "subtitles": "track_markers_or_future_text_track_controller",
            },
            "notes": {
                "timeline_build": "OTIO imports ordered source clips; Resolve controller applies rich effects later.",
                "clip_name_policy": "Clip.name stays the real media filename to improve Resolve relink behavior.",
            },
        }
    }


def build_timeline_metadata(generic_commands: Dict[str, Any], include_basic_transitions: bool) -> Dict[str, Any]:
    return {
        "video_cloner": {
            "compiler_version": VERSION,
            "video_id": generic_commands.get("video_id"),
            "source_schema": generic_commands.get("schema"),
            "generic_schema_version": generic_commands.get("schema_version"),
            "generic_compiler_version": generic_commands.get("compiler_version"),
            "global_style": generic_commands.get("global_style") or {},
            "caption_style_resolved": generic_commands.get("caption_style_resolved") or {},
            "summary": generic_commands.get("summary") or {},
            "operation_counts": operation_counts(generic_commands),
            "precision_policy": {
                "source_ranges": "frame_based_when_available",
                "timeline_ranges": "frame_based_when_available",
                "uses_source_start_frame": True,
                "uses_source_end_frame": True,
                "uses_timeline_start_frame": True,
                "uses_timeline_end_frame": True,
                "timeline_rebuild_policy": "Resolve/OTIO importer creates timeline from ordered clips",
            },
            "marker_contract": {
                "clip_action_markers": "VC_CMD_*",
                "clip_operation_markers": "VC_ZOOM_*, VC_SPEED_*, VC_TRANSITION_IN_CLIP_*",
                "track_transition_markers": "VC_TRANSITION_*",
                "track_subtitle_markers": "VC_SUB_*",
            },
            "controller_next_step": {
                "script": "resolve_apply_video_cloner_metadata.py",
                "purpose": "apply animated Fusion zooms and future native Resolve layers from generic JSON",
                "note": "OTIO metadata is supplemental; generic_edit_commands.json remains source of truth.",
            },
            "basic_otio_transitions": {
                "enabled": bool(include_basic_transitions),
                "default": "disabled because Resolve OTIO transition import may be inconsistent",
            },
        }
    }


# -----------------------------
# Clip / marker builders
# -----------------------------

def add_rich_clip_markers(
    clip: otio.schema.Clip,
    cmd: Dict[str, Any],
    source_start_frame: int,
    duration_frames: int,
    timeline_start_frame: int,
    fps: float,
    include_markers: bool = True,
) -> int:
    """
    Add source-local clip markers. These are visual/debug references after import.
    The Resolve controller still reads generic_edit_commands.json as source of truth.
    """
    markers_before = len(clip.markers)
    action_type = get_action_type(cmd)
    index = get_command_index(cmd, get_int(cmd.get("shot_id"), 0))
    command_name = f"VC_CMD_{index:03d}_{slug(action_type)}"

    add_clip_marker_if_enabled(
        clip=clip,
        include_markers=include_markers,
        name=command_name,
        start_frame=0,
        duration_frames=max(1, min(duration_frames, int(round(fps * 0.25)))),
        fps=fps,
        color="GREEN",
        metadata=vc_marker_metadata(
            marker_type="command_action",
            cmd=cmd,
            extra={
                "timeline_start_frame": timeline_start_frame,
                "source_start_frame": source_start_frame,
                "duration_frames": duration_frames,
            },
        ),
    )

    for op in get_operations(cmd):
        op_name = str(op.get("operation") or "unknown")
        params = op.get("parameters") or {}
        base_extra = {
            "timeline_start_frame": timeline_start_frame,
            "source_start_frame": source_start_frame,
            "duration_frames": duration_frames,
            "apply_with_resolve_controller": True,
        }

        if op_name == "transform_zoom":
            keyframes = params.get("keyframes") or op.get("keyframes") or []
            marker_duration = duration_frames

            add_clip_marker_if_enabled(
                clip=clip,
                include_markers=include_markers,
                name=f"VC_ZOOM_{index:03d}_{slug(params.get('direction', 'unknown'))}",
                start_frame=0,
                duration_frames=marker_duration,
                fps=fps,
                color="PURPLE",
                metadata=vc_marker_metadata(
                    marker_type="transform_zoom",
                    cmd=cmd,
                    op=op,
                    extra={
                        **base_extra,
                        "effect_target": "fusion_transform_size",
                        "keyframes": keyframes,
                    },
                ),
            )

        elif op_name == "speed_ramp":
            segments = params.get("segments") or op.get("segments") or []
            add_clip_marker_if_enabled(
                clip=clip,
                include_markers=include_markers,
                name=f"VC_SPEED_{index:03d}",
                start_frame=0,
                duration_frames=duration_frames,
                fps=fps,
                color="RED",
                metadata=vc_marker_metadata(
                    marker_type="speed_ramp",
                    cmd=cmd,
                    op=op,
                    extra={
                        **base_extra,
                        "effect_target": "retime_curve",
                        "segments": segments,
                    },
                ),
            )

        elif op_name == "beat_cut":
            nearest = params.get("nearest_beat_to_end") or params.get("nearest_beat_to_start") or {}
            beat_time = nearest.get("time") if isinstance(nearest, dict) else None
            beat_frame = None
            if beat_time is not None:
                beat_frame = seconds_to_frames(beat_time, fps) - source_start_frame

            local_frame = marker_start_local_from_relative(beat_frame or duration_frames - 1, duration_frames)
            add_clip_marker_if_enabled(
                clip=clip,
                include_markers=include_markers,
                name=f"VC_BEAT_{index:03d}",
                start_frame=local_frame,
                duration_frames=max(1, int(round(fps * 0.15))),
                fps=fps,
                color="CYAN",
                metadata=vc_marker_metadata(
                    marker_type="beat_cut",
                    cmd=cmd,
                    op=op,
                    extra={
                        **base_extra,
                        "beat_frame_local": local_frame,
                    },
                ),
            )

        elif op_name == "transition_hint":
            cut_frame_abs = params.get("cut_frame")
            if cut_frame_abs is None:
                cut_frame_abs = source_start_frame + duration_frames - 1
            local_frame = marker_start_local_from_relative(get_int(cut_frame_abs) - source_start_frame, duration_frames)

            add_clip_marker_if_enabled(
                clip=clip,
                include_markers=include_markers,
                name=f"VC_TRANSITION_IN_CLIP_{index:03d}_{slug(params.get('transition_type', 'hint'))}",
                start_frame=local_frame,
                duration_frames=max(1, get_int(params.get("duration_frames"), int(round(fps * 0.25)))),
                fps=fps,
                color="YELLOW",
                metadata=vc_marker_metadata(
                    marker_type="transition_hint_in_clip",
                    cmd=cmd,
                    op=op,
                    extra={
                        **base_extra,
                        "effect_target": "transition",
                        "local_frame": local_frame,
                    },
                ),
            )

        else:
            add_clip_marker_if_enabled(
                clip=clip,
                include_markers=include_markers,
                name=f"VC_OP_{index:03d}_{slug(op_name)}",
                start_frame=0,
                duration_frames=max(1, min(duration_frames, int(round(fps * 0.25)))),
                fps=fps,
                color="BLUE",
                metadata=vc_marker_metadata(
                    marker_type="generic_operation",
                    cmd=cmd,
                    op=op,
                    extra=base_extra,
                ),
            )

    return len(clip.markers) - markers_before


def build_video_clip(
    cmd: Dict[str, Any],
    source_video_url: str,
    source_video_path: Optional[str],
    fps: float,
    media_available_frames: int,
    timeline_start_frame: int,
    duration_frames: int,
    include_metadata: bool = True,
    include_markers: bool = True,
) -> Tuple[otio.schema.Clip, int]:
    source_start_frame, source_duration_frames = source_range_from_command(cmd, fps)

    source_video_filename = Path(source_video_path).name if source_video_path else "source_video"

    media_ref = otio.schema.ExternalReference(
        target_url=source_video_url,
        available_range=tr(0, media_available_frames, fps),
        metadata={
            "video_cloner": {
                "source_video_note": "proxy video used as media reference unless overridden by --source-video",
                "source_video_filename": source_video_filename,
            }
        } if include_metadata else {},
    )
    media_ref.name = source_video_filename

    clip = otio.schema.Clip(
        # Keep real media filename for Resolve relink behavior.
        name=source_video_filename,
        media_reference=media_ref,
        source_range=tr(source_start_frame, source_duration_frames, fps),
        metadata=build_clip_metadata(cmd, timeline_start_frame, duration_frames, fps) if include_metadata else {},
    )

    markers_added = 0
    if include_markers:
        markers_added = add_rich_clip_markers(
            clip=clip,
            cmd=cmd,
            source_start_frame=source_start_frame,
            duration_frames=source_duration_frames,
            timeline_start_frame=timeline_start_frame,
            fps=fps,
            include_markers=include_markers,
        )

    return clip, markers_added


def transition_kind_from_type(transition_type: Any) -> otio.schema.TransitionTypes:
    text = str(transition_type or "").lower()
    # OTIO only has SMPTE_Dissolve and Custom in the core schema.
    if "dissolve" in text or "fade" in text or "dip" in text:
        return otio.schema.TransitionTypes.SMPTE_Dissolve
    return otio.schema.TransitionTypes.Custom


def get_transition_operation(cmd: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return find_operation(cmd, "transition_hint")


def transition_duration_frames(op: Optional[Dict[str, Any]], fps: float) -> int:
    if not op:
        return 0
    params = op.get("parameters") or {}
    duration_frames = get_int(params.get("duration_frames"), 0)
    if duration_frames <= 0:
        duration_seconds = get_float(params.get("duration_seconds"), 0.0)
        if duration_seconds > 0:
            duration_frames = max(1, int(round(duration_seconds * fps)))
    if duration_frames <= 0:
        duration_frames = max(2, int(round(fps * 0.25)))
    return max(1, min(duration_frames, int(round(fps * 1.0))))


def can_insert_basic_transition(cmd: Dict[str, Any], op: Optional[Dict[str, Any]], duration_frames: int) -> Tuple[bool, str]:
    if not op or duration_frames <= 0:
        return False, "missing_transition_operation"

    params = op.get("parameters") or {}
    confidence = str(params.get("confidence") or "").lower()
    transition_type = str(params.get("transition_type") or "").lower()

    if confidence and confidence != "high":
        return False, f"confidence_not_high:{confidence}"

    if not transition_type or "candidate" in transition_type or transition_type in {"hard_cut", "unknown_or_simple_cut"}:
        return False, f"non_actionable_transition_type:{transition_type}"

    handle_check = params.get("handle_check") or {}
    if isinstance(handle_check, dict):
        if handle_check.get("ok") is False:
            return False, "handle_check_failed"

    return True, "ok"


def build_basic_otio_transition(cmd: Dict[str, Any], op: Dict[str, Any], duration_frames: int, fps: float) -> otio.schema.Transition:
    params = op.get("parameters") or {}
    half = max(1, duration_frames // 2)
    rest = max(1, duration_frames - half)

    transition = otio.schema.Transition(
        name=f"VC_BASIC_TRANSITION_{get_command_index(cmd, get_int(cmd.get('shot_id'), 0)):03d}_{slug(params.get('transition_type', 'transition'))}",
        transition_type=transition_kind_from_type(params.get("transition_type")),
        in_offset=rt(half, fps),
        out_offset=rt(rest, fps),
        metadata=vc_marker_metadata(
            marker_type="basic_otio_transition",
            cmd=cmd,
            op=op,
            extra={
                "warning": "Optional OTIO transition. Resolve import support may vary.",
                "duration_frames": duration_frames,
                "duration_seconds": frames_to_seconds(duration_frames, fps),
            },
        ),
    )
    return transition


def add_transition_track_marker(
    track: otio.schema.Track,
    cmd: Dict[str, Any],
    op: Dict[str, Any],
    timeline_cut_frame: int,
    fps: float,
    include_markers: bool,
) -> int:
    params = op.get("parameters") or {}
    duration_frames = transition_duration_frames(op, fps)
    index = get_command_index(cmd, get_int(cmd.get("shot_id"), 0))

    add_track_marker_if_enabled(
        track=track,
        include_markers=include_markers,
        name=f"VC_TRANSITION_{index:03d}_{slug(params.get('transition_type', 'hint'))}",
        timeline_start_frame=max(0, timeline_cut_frame),
        duration_frames=duration_frames,
        fps=fps,
        color="YELLOW",
        metadata=vc_marker_metadata(
            marker_type="transition_track_marker",
            cmd=cmd,
            op=op,
            extra={
                "timeline_cut_frame": timeline_cut_frame,
                "duration_frames": duration_frames,
                "placement": params.get("placement"),
                "side": params.get("side"),
                "effect_target": "transition",
            },
        ),
    )
    return 1 if include_markers else 0


def build_video_track(
    generic_commands: Dict[str, Any],
    source_video_url: str,
    source_video_path: Optional[str],
    fps: float,
    include_metadata: bool = True,
    include_markers: bool = True,
    include_transition_markers: bool = True,
    include_basic_transitions: bool = False,
) -> Tuple[otio.schema.Track, Dict[str, Any]]:
    media_available_frames = get_frame_count(generic_commands, fps)

    track = otio.schema.Track(
        name="V1_VideoCloner",
        kind=otio.schema.TrackKind.Video,
        metadata={
            "video_cloner": {
                "track_type": "video",
                "compiler_version": VERSION,
                "markers_role": "clip/action/transition references",
                "basic_otio_transitions_enabled": bool(include_basic_transitions),
            }
        } if include_metadata else {},
    )

    stats = {
        "video_clips": 0,
        "clip_markers": 0,
        "transition_track_markers": 0,
        "basic_otio_transitions_inserted": 0,
        "basic_otio_transitions_skipped": [],
    }

    running_timeline_frame = 0
    timeline_items = generic_commands.get("timeline") or []

    for index, cmd in enumerate(timeline_items, start=1):
        timeline_start_frame, timeline_duration_frames = timeline_range_from_command(
            cmd=cmd,
            fallback_start_frame=running_timeline_frame,
            fps=fps,
        )

        clip, marker_count = build_video_clip(
            cmd=cmd,
            source_video_url=source_video_url,
            source_video_path=source_video_path,
            fps=fps,
            media_available_frames=media_available_frames,
            timeline_start_frame=timeline_start_frame,
            duration_frames=timeline_duration_frames,
            include_metadata=include_metadata,
            include_markers=include_markers,
        )

        track.append(clip)
        stats["video_clips"] += 1
        stats["clip_markers"] += marker_count

        transition_op = get_transition_operation(cmd)
        if transition_op:
            params = transition_op.get("parameters") or {}
            timeline_cut_frame = get_int(
                params.get("timeline_cut_frame"),
                timeline_start_frame + timeline_duration_frames - 1,
            )

            if include_transition_markers and include_markers:
                stats["transition_track_markers"] += add_transition_track_marker(
                    track=track,
                    cmd=cmd,
                    op=transition_op,
                    timeline_cut_frame=timeline_cut_frame,
                    fps=fps,
                    include_markers=True,
                )

            duration_frames = transition_duration_frames(transition_op, fps)
            allowed, reason = can_insert_basic_transition(cmd, transition_op, duration_frames)

            if include_basic_transitions and allowed and index < len(timeline_items):
                track.append(build_basic_otio_transition(cmd, transition_op, duration_frames, fps))
                stats["basic_otio_transitions_inserted"] += 1
            elif include_basic_transitions:
                stats["basic_otio_transitions_skipped"].append({
                    "command_id": cmd.get("command_id"),
                    "shot_id": cmd.get("shot_id"),
                    "reason": reason,
                })

        running_timeline_frame = max(running_timeline_frame, timeline_start_frame + timeline_duration_frames)

    return track, stats


def build_audio_track(generic_commands: Dict[str, Any], audio_url: str, fps: float, include_metadata: bool = True) -> otio.schema.Track:
    source = generic_commands.get("source") or {}
    duration_seconds = get_float(source.get("duration_seconds"), 0.0)
    duration_frames = max(1, int(round(duration_seconds * fps)))

    audio_filename = Path(audio_url).name if audio_url else "source_audio"
    if str(audio_filename).lower().startswith("file:"):
        audio_filename = Path(str(audio_url).replace("file:///", "")).name

    media_ref = otio.schema.ExternalReference(
        target_url=audio_url,
        available_range=tr(0, duration_frames, fps),
        metadata={
            "video_cloner": {
                "source_audio_note": "full-length audio reference",
                "source_audio_filename": audio_filename,
            }
        } if include_metadata else {},
    )
    media_ref.name = audio_filename

    clip = otio.schema.Clip(
        name=audio_filename,
        media_reference=media_ref,
        source_range=tr(0, duration_frames, fps),
        metadata={
            "video_cloner": {
                "track_type": "audio",
                "duration_seconds": duration_seconds,
                "duration_frames": duration_frames,
            }
        } if include_metadata else {},
    )

    track = otio.schema.Track(
        name="A1_SourceAudio",
        kind=otio.schema.TrackKind.Audio,
        metadata={
            "video_cloner": {
                "track_type": "audio",
                "compiler_version": VERSION,
            }
        } if include_metadata else {},
    )
    track.append(clip)
    return track


# -----------------------------
# Subtitle markers
# -----------------------------

def normalize_subtitle_clip(item: Dict[str, Any], index: int, fps: float) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None

    text = str(item.get("text") or item.get("caption") or "").strip()
    if not text:
        return None

    start_frame = item.get("timeline_start_frame")
    end_frame = item.get("timeline_end_frame")

    if start_frame is None:
        start_seconds = item.get("start")
        if start_seconds is None:
            start_seconds = item.get("timeline_start")
        if start_seconds is None:
            start_seconds = item.get("start_seconds")
        start_frame = seconds_to_frames(start_seconds, fps, 0)

    if end_frame is None:
        end_seconds = item.get("end")
        if end_seconds is None:
            end_seconds = item.get("timeline_end")
        if end_seconds is None:
            end_seconds = item.get("end_seconds")
        if end_seconds is not None:
            end_frame = seconds_to_frames(end_seconds, fps, get_int(start_frame, 0) + int(round(fps)))
        else:
            duration_seconds = get_float(item.get("duration"), get_float(item.get("duration_seconds"), 1.0))
            end_frame = get_int(start_frame, 0) + max(1, int(round(duration_seconds * fps)))

    start_i = max(0, get_int(start_frame, 0))
    end_i = max(start_i + 1, get_int(end_frame, start_i + int(round(fps))))

    return {
        "index": index,
        "text": text,
        "start_frame": start_i,
        "end_frame": end_i,
        "duration_frames": max(1, end_i - start_i),
        "source": item,
    }


def get_subtitle_clips(generic_commands: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = generic_commands.get("subtitle_clips")
    if isinstance(raw, list):
        return raw

    # Backward/alternate nesting support.
    timeline = generic_commands.get("timeline") or []
    out: List[Dict[str, Any]] = []
    for cmd in timeline:
        for sub in cmd.get("subtitle_clips") or []:
            if isinstance(sub, dict):
                out.append(sub)
    return out


def add_subtitle_markers(
    video_track: otio.schema.Track,
    generic_commands: Dict[str, Any],
    fps: float,
    include_markers: bool = True,
    include_subtitle_markers: bool = True,
) -> Dict[str, Any]:
    raw_subtitles = get_subtitle_clips(generic_commands)
    result = {
        "subtitle_source_count": len(raw_subtitles),
        "subtitle_markers_added": 0,
        "subtitle_markers_skipped": 0,
    }

    if not include_markers or not include_subtitle_markers:
        result["subtitle_markers_skipped"] = len(raw_subtitles)
        return result

    caption_style = generic_commands.get("caption_style_resolved") or {}

    for index, raw in enumerate(raw_subtitles, start=1):
        normalized = normalize_subtitle_clip(raw, index, fps)
        if not normalized:
            result["subtitle_markers_skipped"] += 1
            continue

        metadata = {
            "video_cloner": {
                "schema": "video_cloner_subtitle_marker",
                "compiler_version": VERSION,
                "marker_type": "subtitle_reference",
                "subtitle_index": index,
                "text": normalized["text"],
                "timeline_start_frame": normalized["start_frame"],
                "timeline_end_frame": normalized["end_frame"],
                "duration_frames": normalized["duration_frames"],
                "caption_style_resolved": caption_style,
                "source": normalized["source"],
                "apply_with_resolve_controller": True,
                "effect_target": "subtitle_or_text_plus",
            }
        }

        video_track.markers.append(
            make_marker(
                name=f"VC_SUB_{index:04d}",
                start_frame=normalized["start_frame"],
                duration_frames=normalized["duration_frames"],
                fps=fps,
                color="BLUE",
                metadata=metadata,
            )
        )
        result["subtitle_markers_added"] += 1

    return result


# -----------------------------
# Timeline builder
# -----------------------------

def build_otio_timeline(
    generic_commands: Dict[str, Any],
    source_video_url: str,
    source_video_path: Optional[str],
    source_audio_url: Optional[str] = None,
    include_metadata: bool = True,
    include_markers: bool = True,
    include_transition_markers: bool = True,
    include_subtitle_markers: bool = True,
    include_basic_transitions: bool = False,
) -> Tuple[otio.schema.Timeline, Dict[str, Any]]:
    fps = get_fps(generic_commands)
    video_id = generic_commands.get("video_id") or "video_cloner_timeline"

    timeline = otio.schema.Timeline(
        name=f"{safe_name(video_id)}_davinci_otio",
        metadata=build_timeline_metadata(generic_commands, include_basic_transitions) if include_metadata else {},
    )

    video_track, video_stats = build_video_track(
        generic_commands=generic_commands,
        source_video_url=source_video_url,
        source_video_path=source_video_path,
        fps=fps,
        include_metadata=include_metadata,
        include_markers=include_markers,
        include_transition_markers=include_transition_markers,
        include_basic_transitions=include_basic_transitions,
    )

    subtitle_stats = add_subtitle_markers(
        video_track=video_track,
        generic_commands=generic_commands,
        fps=fps,
        include_markers=include_markers,
        include_subtitle_markers=include_subtitle_markers,
    )

    timeline.tracks.append(video_track)

    audio_track_added = False
    if source_audio_url:
        timeline.tracks.append(
            build_audio_track(
                generic_commands=generic_commands,
                audio_url=source_audio_url,
                fps=fps,
                include_metadata=include_metadata,
            )
        )
        audio_track_added = True

    stats = {
        **video_stats,
        **subtitle_stats,
        "audio_track_added": audio_track_added,
    }

    return timeline, stats


def validate_generic_commands(generic_commands: Dict[str, Any]) -> List[str]:
    errors: List[str] = []

    if not isinstance(generic_commands, dict):
        return ["generic commands root must be object"]

    if not generic_commands.get("success"):
        errors.append("generic_commands.success must be true")

    if generic_commands.get("schema") != "generic_edit_commands":
        errors.append("generic_commands.schema must be generic_edit_commands")

    timeline = generic_commands.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        errors.append("generic_commands.timeline must be a non-empty list")

    source_video = get_source_video(generic_commands)
    if not source_video:
        errors.append("generic_commands.source.source_video is missing")

    fps = get_fps(generic_commands)
    if fps <= 0:
        errors.append("fps must be > 0")

    for idx, cmd in enumerate(timeline or [], start=1):
        if not isinstance(cmd, dict):
            errors.append(f"timeline[{idx}] must be object")
            continue

        start, duration = source_range_from_command(cmd, fps)
        if duration <= 0:
            errors.append(f"timeline[{idx}] has invalid source duration")

        if start < 0:
            errors.append(f"timeline[{idx}] has negative source start frame")

    return errors


def count_markers(timeline: otio.schema.Timeline) -> Dict[str, int]:
    counts = {
        "timeline_markers": len(getattr(timeline, "markers", []) or []),
        "track_markers": 0,
        "clip_markers": 0,
        "total": 0,
    }

    for track in timeline.tracks:
        counts["track_markers"] += len(getattr(track, "markers", []) or [])
        for item in track:
            if hasattr(item, "markers"):
                counts["clip_markers"] += len(item.markers)

    counts["total"] = counts["timeline_markers"] + counts["track_markers"] + counts["clip_markers"]
    return counts


def count_track_items(timeline: otio.schema.Timeline) -> Dict[str, int]:
    counts = {
        "tracks": len(timeline.tracks),
        "clips": 0,
        "transitions": 0,
        "other": 0,
    }

    for track in timeline.tracks:
        for item in track:
            if isinstance(item, otio.schema.Clip):
                counts["clips"] += 1
            elif isinstance(item, otio.schema.Transition):
                counts["transitions"] += 1
            else:
                counts["other"] += 1

    return counts


# -----------------------------
# CLI
# -----------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile generic edit commands into DaVinci-friendly OTIO using official OpenTimelineIO writer."
    )

    parser.add_argument("--generic", required=True, help="Path to generic_edit_commands.json")
    parser.add_argument("--output", required=True, help="Path to output .otio file")

    parser.add_argument(
        "--source-video",
        default=None,
        help="Optional media file override. Use this to point OTIO to full-res video instead of proxy.",
    )
    parser.add_argument(
        "--source-audio",
        default=None,
        help="Optional audio file override. Defaults to generic source_audio when available.",
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="Do not include audio track in OTIO.",
    )

    parser.add_argument(
        "--no-metadata",
        action="store_true",
        help="Do not include Video Cloner metadata. Useful for Resolve import debugging.",
    )
    parser.add_argument(
        "--no-markers",
        action="store_true",
        help="Do not include VC_* markers. Useful for Resolve import debugging.",
    )
    parser.add_argument(
        "--no-transition-markers",
        action="store_true",
        help="Do not include track-level transition reference markers.",
    )
    parser.add_argument(
        "--no-subtitle-markers",
        action="store_true",
        help="Do not include track-level subtitle reference markers.",
    )
    parser.add_argument(
        "--include-basic-transitions",
        action="store_true",
        help="Experimental: insert basic OTIO Transition objects for high-confidence transition_hint ops. Default is off.",
    )
    parser.add_argument(
        "--media-url-mode",
        default="resolve_unescaped_file_uri",
        choices=["resolve_unescaped_file_uri", "file_uri", "native", "posix", "basename"],
        help="How media references are written into OTIO target_url. Default avoids percent-encoded spaces for Resolve auto-linking.",
    )

    args = parser.parse_args()

    generic_commands = load_json(args.generic)

    errors = validate_generic_commands(generic_commands)
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, indent=2), flush=True)
        sys.exit(1)

    source_video = args.source_video or get_source_video(generic_commands)
    source_audio = None if args.no_audio else (
        args.source_audio or get_source_audio(generic_commands)
    )

    media_warnings: List[str] = []
    if source_video and not Path(source_video).expanduser().exists():
        media_warnings.append(f"source_video does not exist on disk: {source_video}")
    if source_audio and not Path(source_audio).expanduser().exists():
        media_warnings.append(f"source_audio does not exist on disk: {source_audio}")

    source_video_url = path_to_resolve_media_target(source_video, args.media_url_mode)
    source_audio_url = path_to_resolve_media_target(source_audio, args.media_url_mode) if source_audio else None

    include_metadata = not args.no_metadata
    include_markers = not args.no_markers
    include_transition_markers = include_markers and not args.no_transition_markers
    include_subtitle_markers = include_markers and not args.no_subtitle_markers

    timeline, build_stats = build_otio_timeline(
        generic_commands=generic_commands,
        source_video_url=source_video_url,
        source_video_path=source_video,
        source_audio_url=source_audio_url,
        include_metadata=include_metadata,
        include_markers=include_markers,
        include_transition_markers=include_transition_markers,
        include_subtitle_markers=include_subtitle_markers,
        include_basic_transitions=args.include_basic_transitions,
    )

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    otio.adapters.write_to_file(timeline, args.output)

    fps = get_fps(generic_commands)
    clips_count = len(generic_commands.get("timeline") or [])
    marker_counts = count_markers(timeline)
    item_counts = count_track_items(timeline)

    print(json.dumps({
        "ok": True,
        "compiler_version": VERSION,
        "output": os.path.abspath(args.output),
        "video_id": generic_commands.get("video_id"),
        "fps": fps,
        "clips_count": clips_count,
        "item_counts": item_counts,
        "marker_counts": marker_counts,
        "source_video": source_video,
        "source_audio": source_audio,
        "source_video_url": source_video_url,
        "source_video_clip_name": Path(source_video).name if source_video else None,
        "source_audio_url": source_audio_url,
        "source_audio_clip_name": Path(source_audio).name if source_audio else None,
        "media_url_mode": args.media_url_mode,
        "include_metadata": include_metadata,
        "include_markers": include_markers,
        "include_transition_markers": include_transition_markers,
        "include_subtitle_markers": include_subtitle_markers,
        "include_basic_transitions": bool(args.include_basic_transitions),
        "build_stats": build_stats,
        "operation_counts": operation_counts(generic_commands),
        "writer": "opentimelineio.adapters.write_to_file",
        "warnings": media_warnings,
        "next_step": "Import .otio into DaVinci, then run resolve_apply_video_cloner_metadata.py for animated Fusion zoom and other native layers.",
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
