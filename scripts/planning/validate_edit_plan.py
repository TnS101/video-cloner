#!/usr/bin/env python3
"""
validate_edit_plan.py

Validator for Video Cloner edit_plan.json.

Purpose:
    Validate the editor-agnostic edit plan against analysis.json before compiling it
    into rich generic_edit_commands.json.

This validator does not create editor-specific instructions. It makes sure the plan
    is deterministic, executable, and safe for downstream compilers.

Current contract targets:
    - compile_generic_edit.py v2 rich editor-agnostic commands
    - DaVinci Resolve controller v0.4+ Fusion animated zoom layer
    - future speed ramp, transition, and subtitle compilers

Important architecture rule:
    This file validates the plan and analysis contract only.
    It does not modify Resolve, OTIO, subtitles, transitions, or speed ramps directly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION = "validate_edit_plan_v4_2_zoom_candidate_non_actionable"

PRIMARY_ACTIONS = {
    "hold",
    "cut",
    "beat_cut",
    "zoom_in",
    "zoom_out",
    "speed_ramp",
}

# Layer actions are allowed as first-class IR hints. The current generic compiler
# mostly compiles primary shot actions + analysis-derived subtitles/transitions,
# but keeping layer actions valid prevents the LLM/planner layer from throwing
# useful metadata away.
LAYER_ACTIONS = {
    "transition",
    "transition_hint",
    "subtitle",
    "subtitle_focus",
    "caption",
    "caption_style",
    "camera_move",
    "effect",
    "text",
    "overlay",
    "audio",
    "audio_duck",
    "sfx",
    "broll",
    "color_grade",
    "crop",
    "reframe",
}

ALLOWED_ACTIONS = PRIMARY_ACTIONS | LAYER_ACTIONS
DISALLOWED_ACTIONS = set()

ALLOWED_CONFIDENCE = {"low", "medium", "high"}
ALLOWED_PACE = {"slow", "medium", "fast"}
ALLOWED_CAPTION_STYLE_MODES = {"detected", "none", "manual"}

REQUIRED_PRIMARY_ACTION_FIELDS = {
    "type",
    "rule_id",
    "confidence",
    "priority_score",
    "intent",
    "compiler_hints",
}

REQUIRED_PRIMARY_COMPILER_HINT_KEYS = {
    "strength",
    "sync_to_beat",
    "preferred_timing",
}

VALID_SPEED_RAMP_INTENSITIES = {"medium", "high", "very_high"}
OBSERVATIONAL_TRANSITION_CANDIDATES = {
    "slide_transition_candidate",
    "whip_pan_candidate",
}
UNSUPPORTED_EXECUTABLE_TRANSITIONS = {"slide_transition", "whip_pan"}
MIN_TRANSITION_FRAMES = 6
DEFAULT_TRANSITION_FRAMES = 12


# -------------------------
# IO / small utilities
# -------------------------


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: Dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def err(message: str, **extra: Any) -> Dict[str, Any]:
    item = {"message": message}
    item.update(extra)
    return item


def warn(message: str, **extra: Any) -> Dict[str, Any]:
    item = {"message": message}
    item.update(extra)
    return item


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


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


# -------------------------
# Analysis helpers
# -------------------------


def get_analysis_shots(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    shots = analysis.get("timeline", {}).get("shots", [])
    return shots if isinstance(shots, list) else []


def build_analysis_index(analysis: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    by_id: Dict[int, Dict[str, Any]] = {}
    for shot in get_analysis_shots(analysis):
        if not isinstance(shot, dict):
            continue
        shot_id = shot.get("shot_id")
        if shot_id is not None:
            by_id[int(shot_id)] = shot
    return by_id


def get_motion(shot: Dict[str, Any]) -> Dict[str, Any]:
    return shot.get("motion") or {}


def get_edit_signals(shot: Dict[str, Any]) -> Dict[str, Any]:
    return shot.get("edit_signals") or {}


def get_transition_to_next(shot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    transition = shot.get("transition_to_next")
    return transition if isinstance(transition, dict) else None


def get_fps(analysis: Dict[str, Any]) -> float:
    fps = get_float((analysis.get("job") or {}).get("fps"), 0.0)
    if fps <= 0:
        fps = get_float((analysis.get("summary") or {}).get("fps"), 0.0)
    return fps


def shot_start_frame(shot: Dict[str, Any], fps: float) -> int:
    if shot.get("start_frame") is not None:
        return get_int(shot.get("start_frame"), 0)
    return int(round(get_float(shot.get("start_seconds"), 0.0) * fps))


def shot_end_frame(shot: Dict[str, Any], fps: float) -> int:
    if shot.get("end_frame") is not None:
        return get_int(shot.get("end_frame"), 0)
    return int(round(get_float(shot.get("end_seconds"), 0.0) * fps))


def shot_duration_frames(shot: Dict[str, Any], fps: float) -> int:
    start = shot_start_frame(shot, fps)
    end = shot_end_frame(shot, fps)
    if end > start:
        return max(1, end - start)
    return max(1, int(round(get_float(shot.get("duration_seconds"), 0.0) * fps)))


def shot_duration_seconds(shot: Dict[str, Any]) -> float:
    duration = get_float(shot.get("duration_seconds"), 0.0)
    if duration > 0:
        return duration
    start = get_float(shot.get("start_seconds"), 0.0)
    end = get_float(shot.get("end_seconds"), 0.0)
    return max(0.0, end - start)


def next_shot_by_id(analysis_index: Dict[int, Dict[str, Any]], shot_id: int) -> Optional[Dict[str, Any]]:
    return analysis_index.get(shot_id + 1)


# -------------------------
# Transcript / caption helpers
# -------------------------


def find_first_list_by_keys(root: Any, keys: Tuple[str, ...], max_depth: int = 5) -> List[Any]:
    """Small recursive search used only for flexible analysis JSON variants."""
    if max_depth < 0:
        return []
    if isinstance(root, dict):
        for key in keys:
            value = root.get(key)
            if isinstance(value, list):
                return value
        for value in root.values():
            found = find_first_list_by_keys(value, keys, max_depth - 1)
            if found:
                return found
    elif isinstance(root, list):
        for value in root:
            found = find_first_list_by_keys(value, keys, max_depth - 1)
            if found:
                return found
    return []


def get_transcript_segments(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates = []

    direct_transcript = analysis.get("transcript")
    if isinstance(direct_transcript, dict):
        candidates.append(direct_transcript.get("segments"))
        candidates.append(direct_transcript.get("word_segments"))

    timeline = analysis.get("timeline") or {}
    if isinstance(timeline, dict):
        tl_transcript = timeline.get("transcript")
        if isinstance(tl_transcript, dict):
            candidates.append(tl_transcript.get("segments"))
        candidates.append(timeline.get("transcript_segments"))
        candidates.append(timeline.get("subtitle_segments"))

    layers = analysis.get("layers") or {}
    if isinstance(layers, dict):
        layer_transcript = layers.get("transcript")
        if isinstance(layer_transcript, dict):
            candidates.append(layer_transcript.get("segments"))

    # Fallback for nested compact outputs.
    candidates.append(find_first_list_by_keys(analysis, ("segments", "transcript_segments", "subtitle_segments"), max_depth=4))

    for candidate in candidates:
        if isinstance(candidate, list) and candidate:
            return [x for x in candidate if isinstance(x, dict)]
    return []


def get_caption_style_data(analysis: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("caption_style", "captionStyle"):
        value = analysis.get(key)
        if isinstance(value, dict):
            return value

    timeline = analysis.get("timeline") or {}
    if isinstance(timeline, dict):
        value = timeline.get("caption_style")
        if isinstance(value, dict):
            return value

    layers = analysis.get("layers") or {}
    if isinstance(layers, dict):
        value = layers.get("caption_style")
        if isinstance(value, dict):
            return value

    # Your OCR analyzer often uses subtitle_style_summary / subtitle_groups.
    if any(key in analysis for key in ("subtitle_style_summary", "subtitle_groups")):
        return {
            "summary": analysis.get("subtitle_style_summary"),
            "groups": analysis.get("subtitle_groups"),
            "source": "root_subtitle_style_fields",
        }

    return {}


# -------------------------
# Rule helpers
# -------------------------


def is_push_in(shot: Dict[str, Any]) -> bool:
    motion = get_motion(shot)
    motion_type = str(motion.get("motion_type") or "").lower()
    motion_family = str(motion.get("motion_family") or "").lower()
    return motion_family == "push_in" or "push_in" in motion_type


def is_pull_out(shot: Dict[str, Any]) -> bool:
    motion = get_motion(shot)
    motion_type = str(motion.get("motion_type") or "").lower()
    motion_family = str(motion.get("motion_family") or "").lower()
    return motion_family == "pull_out" or "pull_out" in motion_type


def is_static(shot: Dict[str, Any]) -> bool:
    motion = get_motion(shot)
    motion_type = str(motion.get("motion_type") or "").lower()
    motion_family = str(motion.get("motion_family") or "").lower()
    return motion_family == "static" or motion_type == "static"


def valid_speed_ramp(shot: Dict[str, Any]) -> bool:
    """Motion heuristics alone never authorize an executable retime."""
    return False


def expected_speed_ramp_observation(shot: Dict[str, Any]) -> Dict[str, Any]:
    motion = get_motion(shot)
    signals = get_edit_signals(shot)
    candidate = bool(signals.get("speed_ramp_candidate"))
    return {
        "candidate": candidate,
        "actionable": False,
        "authority": "motion_heuristic_only",
        "motion_intensity": motion.get("motion_intensity"),
        "motion_confidence": motion.get("confidence"),
        "reason": (
            "motion analysis marked a speed-ramp candidate; exact retime authority "
            "requires separate source-backed evidence"
            if candidate
            else "motion analysis did not mark a speed-ramp candidate"
        ),
    }


def validate_speed_ramp_observation(
    item: Dict[str, Any],
    shot: Dict[str, Any],
) -> List[Dict[str, Any]]:
    shot_id = int(shot.get("shot_id"))
    observations = item.get("observations")
    if not isinstance(observations, dict):
        return [err("timeline item missing observations object", shot_id=shot_id)]

    actual = observations.get("speed_ramp_candidate")
    expected = expected_speed_ramp_observation(shot)
    if actual != expected:
        return [
            err(
                "speed_ramp_candidate observation mismatch",
                shot_id=shot_id,
                expected=expected,
                actual=actual,
            )
        ]
    return []


def expected_zoom_observation(shot: Dict[str, Any]) -> Dict[str, Any]:
    motion = get_motion(shot)
    camera_motion = motion.get("camera_motion") or {}
    motion_based_zoom = motion.get("motion_based_zoom") or {}
    candidate = bool(motion.get("zoom_candidate"))
    return {
        "candidate": candidate,
        "actionable": False,
        "authority": "motion_heuristic_only",
        "source": "motion_affine_scale_delta",
        "direction": motion.get("zoom_direction") if candidate else None,
        "confidence": motion_based_zoom.get("confidence"),
        "motion_family": motion.get("motion_family"),
        "motion_type": motion.get("motion_type"),
        "motion_intensity": motion.get("motion_intensity"),
        "avg_scale_delta": camera_motion.get("avg_scale_delta"),
        "reason": (
            "affine scale motion marked a zoom candidate; editable zoom authority "
            "requires separate source-backed transform evidence"
            if candidate
            else "affine scale motion did not mark a zoom candidate"
        ),
    }


def validate_zoom_observation(
    item: Dict[str, Any],
    shot: Dict[str, Any],
) -> List[Dict[str, Any]]:
    shot_id = int(shot.get("shot_id"))
    observations = item.get("observations")
    if not isinstance(observations, dict):
        return [err("timeline item missing observations object", shot_id=shot_id)]

    actual = observations.get("zoom_candidate")
    expected = expected_zoom_observation(shot)
    if actual != expected:
        return [
            err(
                "zoom_candidate observation mismatch",
                shot_id=shot_id,
                expected=expected,
                actual=actual,
            )
        ]
    return []


def valid_beat_cut(shot: Dict[str, Any]) -> bool:
    signals = get_edit_signals(shot)
    score = get_float(signals.get("cut_priority_score"), 0.0)
    beats = get_int(signals.get("beats_in_shot_count"), 0)
    return score > 0.5 and beats > 0


def valid_hold(shot: Dict[str, Any]) -> bool:
    signals = get_edit_signals(shot)
    score = get_float(signals.get("cut_priority_score"), 1.0)
    return is_static(shot) and score < 0.3


def expected_action_type_for_shot(shot: Dict[str, Any]) -> str:
    motion = get_motion(shot)
    signals = get_edit_signals(shot)

    motion_type = str(motion.get("motion_type") or "")
    motion_family = str(motion.get("motion_family") or "")
    motion_intensity = str(motion.get("motion_intensity") or "")

    cut_priority_score = get_float(signals.get("cut_priority_score"), 0.0)
    beats_in_shot_count = get_int(signals.get("beats_in_shot_count"), 0)
    speed_ramp_candidate = bool(signals.get("speed_ramp_candidate"))

    if speed_ramp_candidate and motion_intensity in VALID_SPEED_RAMP_INTENSITIES:
        return "cut"

    if cut_priority_score > 0.5 and beats_in_shot_count > 0:
        return "beat_cut"

    if bool(motion.get("zoom_candidate")):
        return "cut"

    if cut_priority_score >= 0.3:
        return "cut"

    if motion_family == "static" and cut_priority_score < 0.3:
        return "hold"

    return "cut"


def expected_metadata_for_action(action_type: str, shot: Dict[str, Any]) -> Dict[str, Any]:
    motion = get_motion(shot)
    signals = get_edit_signals(shot)

    motion_intensity = str(motion.get("motion_intensity") or "").lower()
    motion_confidence = str(motion.get("confidence") or "").lower()
    cut_priority_score = get_float(signals.get("cut_priority_score"), 0.0)
    beats = get_int(signals.get("beats_in_shot_count"), 0)
    downbeats = get_int(signals.get("downbeats_in_shot_count"), 0)

    rule_id = "R_FALLBACK_CUT"
    confidence = "medium"
    priority_score = 0.35
    intent = "safe_cut"
    compiler_hints = {
        "strength": "normal",
        "sync_to_beat": False,
        "preferred_timing": "shot_boundary",
    }

    if action_type == "speed_ramp":
        rule_id = "R1_SPEED_RAMP"
        intent = "emphasize_motion_speed_change"

        if motion_intensity == "very_high":
            confidence = "high"
            priority_score = 0.95
            strength = "strong"
        elif motion_intensity == "high":
            confidence = "high"
            priority_score = 0.88
            strength = "strong"
        else:
            confidence = "medium"
            priority_score = 0.78
            strength = "medium"

        compiler_hints = {
            "strength": strength,
            "sync_to_beat": beats > 0,
            "preferred_timing": "within_shot",
            "ramp_style": "smooth",
        }

    elif action_type == "beat_cut":
        rule_id = "R2_BEAT_CUT"
        intent = "sync_cut_to_rhythm"
        confidence = "high" if cut_priority_score >= 0.65 else "medium"
        priority_score = clamp(0.55 + cut_priority_score * 0.35 + min(beats, 4) * 0.025)

        compiler_hints = {
            "strength": "normal",
            "sync_to_beat": True,
            "preferred_timing": "nearest_beat",
            "prefer_downbeat": downbeats > 0,
        }

    elif action_type == "zoom_in":
        rule_id = "R3_ZOOM_IN"
        intent = "enhance_existing_push_in"
        confidence = "high" if motion_confidence == "high" else "medium"
        priority_score = 0.72 if motion_intensity in {"medium", "high", "very_high"} else 0.62

        compiler_hints = {
            "strength": "subtle" if motion_intensity in {"static", "subtle"} else "medium",
            "sync_to_beat": False,
            "preferred_timing": "full_shot",
            "direction": "in",
        }

    elif action_type == "zoom_out":
        rule_id = "R4_ZOOM_OUT"
        intent = "enhance_existing_pull_out"
        confidence = "high" if motion_confidence == "high" else "medium"
        priority_score = 0.72 if motion_intensity in {"medium", "high", "very_high"} else 0.62

        compiler_hints = {
            "strength": "subtle" if motion_intensity in {"static", "subtle"} else "medium",
            "sync_to_beat": False,
            "preferred_timing": "full_shot",
            "direction": "out",
        }

    elif action_type == "cut":
        rule_id = "R5_CUT"
        intent = "safe_cut_or_pacing_cut"
        confidence = "high" if cut_priority_score >= 0.5 else "medium"
        priority_score = clamp(0.35 + cut_priority_score * 0.55)

        compiler_hints = {
            "strength": "normal",
            "sync_to_beat": beats > 0,
            "preferred_timing": "shot_boundary",
        }

    elif action_type == "hold":
        rule_id = "R6_HOLD"
        intent = "preserve_static_or_low_priority_shot"
        confidence = "high" if cut_priority_score < 0.2 else "medium"
        priority_score = clamp(0.3 + (0.3 - min(cut_priority_score, 0.3)))

        compiler_hints = {
            "strength": "none",
            "sync_to_beat": False,
            "preferred_timing": "full_shot",
        }

    return {
        "rule_id": rule_id,
        "confidence": confidence,
        "priority_score": round(priority_score, 4),
        "intent": intent,
        "compiler_hints": compiler_hints,
    }


# -------------------------
# Structure validation
# -------------------------


def validate_structure(edit_plan: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    if not isinstance(edit_plan, dict):
        errors.append(err("edit_plan root must be a JSON object"))
        return errors, warnings

    if edit_plan.get("version") != "1.0":
        errors.append(err("version must be '1.0'", found=edit_plan.get("version")))

    if not nonempty_str(edit_plan.get("video_id")):
        errors.append(err("missing or invalid video_id"))

    global_style = edit_plan.get("global_style")
    if not isinstance(global_style, dict):
        errors.append(err("missing or invalid global_style"))
    else:
        pace = global_style.get("pace")
        if pace not in ALLOWED_PACE:
            errors.append(err("global_style.pace must be slow|medium|fast", found=pace))

        if not isinstance(global_style.get("music_sync"), bool):
            errors.append(err("global_style.music_sync must be boolean"))

        caption_style = global_style.get("caption_style")
        if caption_style not in ALLOWED_CAPTION_STYLE_MODES:
            errors.append(err("global_style.caption_style must be detected|none|manual", found=caption_style))

    if not isinstance(edit_plan.get("timeline"), list):
        errors.append(err("timeline must be a list"))

    return errors, warnings


def validate_analysis_contract(analysis: Dict[str, Any], strict: bool = True) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Validate the analysis JSON fields required by the rich generic compiler.

    When strict=True, missing timing/frame data is an error because downstream
    compilers need deterministic timeline/source frame mapping.
    """
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    fps = get_fps(analysis)
    shots = get_analysis_shots(analysis)
    transcript_segments = get_transcript_segments(analysis)
    caption_style = get_caption_style_data(analysis)

    report: Dict[str, Any] = {
        "fps": fps,
        "shots_count": len(shots),
        "transcript_segments_count": len(transcript_segments),
        "caption_style_present": bool(caption_style),
        "high_confidence_transitions": 0,
        "shots_missing_frame_fields": [],
        "shots_with_bad_timing": [],
    }

    if not isinstance(analysis, dict):
        errors.append(err("analysis root must be object"))
        return errors, warnings, report

    if fps <= 0:
        errors.append(err("analysis job.fps must be > 0 for rich compiler", fps=fps))

    if not shots:
        errors.append(err("analysis.timeline.shots must be a non-empty list"))
        return errors, warnings, report

    seen_ids: List[int] = []
    previous_start_frame: Optional[int] = None
    previous_end_frame: Optional[int] = None

    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            errors.append(err("analysis shot must be object", index=index))
            continue

        shot_id_raw = shot.get("shot_id")
        if shot_id_raw is None:
            errors.append(err("analysis shot missing shot_id", index=index))
            continue

        shot_id = get_int(shot_id_raw, -1)
        seen_ids.append(shot_id)

        required_timing = ["start_seconds", "end_seconds", "duration_seconds"]
        required_frames = ["start_frame", "end_frame"]
        missing_timing = [key for key in required_timing if shot.get(key) is None]
        missing_frames = [key for key in required_frames if shot.get(key) is None]

        if missing_timing:
            item = err("analysis shot missing timing fields", shot_id=shot_id, missing_fields=missing_timing)
            if strict:
                errors.append(item)
            else:
                warnings.append(item)

        if missing_frames:
            report["shots_missing_frame_fields"].append(shot_id)
            item = err("analysis shot missing frame fields", shot_id=shot_id, missing_fields=missing_frames)
            if strict:
                errors.append(item)
            else:
                warnings.append(item)

        start_seconds = get_float(shot.get("start_seconds"), 0.0)
        end_seconds = get_float(shot.get("end_seconds"), 0.0)
        duration_seconds = shot_duration_seconds(shot)
        start_frame = shot_start_frame(shot, fps)
        end_frame = shot_end_frame(shot, fps)
        duration_frames = max(0, end_frame - start_frame)

        if end_seconds <= start_seconds or duration_seconds <= 0:
            report["shots_with_bad_timing"].append(shot_id)
            errors.append(
                err(
                    "analysis shot has invalid seconds timing",
                    shot_id=shot_id,
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                    duration_seconds=duration_seconds,
                )
            )

        if fps > 0 and duration_frames <= 0:
            report["shots_with_bad_timing"].append(shot_id)
            errors.append(
                err(
                    "analysis shot has invalid frame timing",
                    shot_id=shot_id,
                    start_frame=start_frame,
                    end_frame=end_frame,
                    duration_frames=duration_frames,
                )
            )

        if previous_start_frame is not None and start_frame < previous_start_frame:
            warnings.append(
                warn(
                    "analysis shot start_frame order is not monotonic",
                    shot_id=shot_id,
                    start_frame=start_frame,
                    previous_start_frame=previous_start_frame,
                )
            )

        if previous_end_frame is not None and start_frame < previous_end_frame:
            # This is not always fatal because some detectors use inclusive end frames,
            # but it matters for handles/transitions, so keep it visible.
            warnings.append(
                warn(
                    "analysis shot overlaps previous shot by frame timing",
                    shot_id=shot_id,
                    start_frame=start_frame,
                    previous_end_frame=previous_end_frame,
                )
            )

        transition = get_transition_to_next(shot)
        if transition and transition.get("confidence") == "high":
            report["high_confidence_transitions"] += 1

        previous_start_frame = start_frame
        previous_end_frame = end_frame

    duplicates = sorted({shot_id for shot_id in seen_ids if seen_ids.count(shot_id) > 1})
    if duplicates:
        errors.append(err("duplicate shot_ids in analysis.timeline.shots", duplicate_shot_ids=duplicates))

    return errors, warnings, report


# -------------------------
# Action validation
# -------------------------


def validate_action_shape(action: Any, shot_id: int, action_index: int, is_primary_position: bool = False) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    if not isinstance(action, dict):
        errors.append(err("action must be object", shot_id=shot_id, action_index=action_index))
        return errors, warnings

    action_type = action.get("type")

    if action_type in DISALLOWED_ACTIONS:
        errors.append(err("disallowed action type", shot_id=shot_id, action_index=action_index, action_type=action_type))

    if action_type not in ALLOWED_ACTIONS:
        errors.append(
            err(
                "unsupported action type",
                shot_id=shot_id,
                action_index=action_index,
                action_type=action_type,
                allowed=sorted(ALLOWED_ACTIONS),
            )
        )
        return errors, warnings

    is_primary = action_type in PRIMARY_ACTIONS

    reason = action.get("reason")
    if not nonempty_str(reason):
        warnings.append(warn("missing or empty action reason", shot_id=shot_id, action_index=action_index, action_type=action_type))

    # Primary actions are executable shot decisions; they must be fully shaped.
    if is_primary:
        missing_fields = sorted([key for key in REQUIRED_PRIMARY_ACTION_FIELDS if key not in action])
        if missing_fields:
            errors.append(
                err(
                    "primary action missing required fields",
                    shot_id=shot_id,
                    action_index=action_index,
                    action_type=action_type,
                    missing_fields=missing_fields,
                )
            )

        rule_id = action.get("rule_id")
        if not nonempty_str(rule_id):
            errors.append(err("missing action.rule_id", shot_id=shot_id, action_index=action_index, action_type=action_type))

        confidence = action.get("confidence")
        if confidence not in ALLOWED_CONFIDENCE:
            errors.append(
                err(
                    "action.confidence must be low|medium|high",
                    shot_id=shot_id,
                    action_index=action_index,
                    action_type=action_type,
                    confidence=confidence,
                )
            )

        priority_score = action.get("priority_score")
        if not is_number(priority_score):
            errors.append(
                err(
                    "action.priority_score must be numeric",
                    shot_id=shot_id,
                    action_index=action_index,
                    action_type=action_type,
                    priority_score=priority_score,
                )
            )
        elif float(priority_score) < 0 or float(priority_score) > 1:
            errors.append(
                err(
                    "action.priority_score must be between 0 and 1",
                    shot_id=shot_id,
                    action_index=action_index,
                    action_type=action_type,
                    priority_score=priority_score,
                )
            )

        intent = action.get("intent")
        if not nonempty_str(intent):
            errors.append(err("missing action.intent", shot_id=shot_id, action_index=action_index, action_type=action_type))

        compiler_hints = action.get("compiler_hints")
        if not isinstance(compiler_hints, dict):
            errors.append(err("missing or invalid action.compiler_hints", shot_id=shot_id, action_index=action_index, action_type=action_type))
        else:
            missing_keys = sorted(REQUIRED_PRIMARY_COMPILER_HINT_KEYS - set(compiler_hints.keys()))
            if missing_keys:
                errors.append(
                    err(
                        "primary action.compiler_hints missing required keys",
                        shot_id=shot_id,
                        action_index=action_index,
                        action_type=action_type,
                        missing_keys=missing_keys,
                    )
                )

            if "sync_to_beat" in compiler_hints and not isinstance(compiler_hints["sync_to_beat"], bool):
                errors.append(err("compiler_hints.sync_to_beat must be boolean", shot_id=shot_id, action_index=action_index, action_type=action_type))

    # Layer actions are allowed to be lighter. They are additive metadata.
    else:
        if is_primary_position:
            errors.append(
                err(
                    "first action for a shot must be a primary action",
                    shot_id=shot_id,
                    action_index=action_index,
                    action_type=action_type,
                    allowed_primary_actions=sorted(PRIMARY_ACTIONS),
                )
            )

        confidence = action.get("confidence")
        if confidence is not None and confidence not in ALLOWED_CONFIDENCE:
            errors.append(
                err(
                    "layer action.confidence must be low|medium|high when provided",
                    shot_id=shot_id,
                    action_index=action_index,
                    action_type=action_type,
                    confidence=confidence,
                )
            )

        priority_score = action.get("priority_score")
        if priority_score is not None:
            if not is_number(priority_score) or float(priority_score) < 0 or float(priority_score) > 1:
                errors.append(
                    err(
                        "layer action.priority_score must be numeric between 0 and 1 when provided",
                        shot_id=shot_id,
                        action_index=action_index,
                        action_type=action_type,
                        priority_score=priority_score,
                    )
                )

        compiler_hints = action.get("compiler_hints")
        if compiler_hints is not None and not isinstance(compiler_hints, dict):
            errors.append(err("layer action.compiler_hints must be object when provided", shot_id=shot_id, action_index=action_index, action_type=action_type))

    return errors, warnings


def validate_action_against_analysis(
    action: Dict[str, Any],
    shot: Dict[str, Any],
    strict: bool = True,
    enforce_expected_action: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    shot_id = int(shot.get("shot_id"))
    action_type = action.get("type")
    motion = get_motion(shot)
    signals = get_edit_signals(shot)

    expected_action_type = expected_action_type_for_shot(shot)

    if enforce_expected_action and action_type in PRIMARY_ACTIONS and action_type != expected_action_type:
        errors.append(
            err(
                "action type does not match deterministic priority rules",
                shot_id=shot_id,
                action_type=action_type,
                expected_action_type=expected_action_type,
            )
        )

    if action_type == "speed_ramp" and not valid_speed_ramp(shot):
        errors.append(
            err(
                "invalid speed_ramp action; motion heuristic is not retime authority",
                shot_id=shot_id,
                speed_ramp_candidate=signals.get("speed_ramp_candidate"),
                motion_intensity=motion.get("motion_intensity"),
                required_authority="separate source-backed retime evidence",
            )
        )

    elif action_type == "beat_cut" and not valid_beat_cut(shot):
        errors.append(
            err(
                "invalid beat_cut action",
                shot_id=shot_id,
                cut_priority_score=signals.get("cut_priority_score"),
                beats_in_shot_count=signals.get("beats_in_shot_count"),
            )
        )

    elif action_type in {"zoom_in", "zoom_out"}:
        errors.append(
            err(
                "invalid zoom action; motion heuristic is not editable zoom authority",
                shot_id=shot_id,
                action_type=action_type,
                zoom_candidate=motion.get("zoom_candidate"),
                zoom_direction=motion.get("zoom_direction"),
                motion_type=motion.get("motion_type"),
                motion_family=motion.get("motion_family"),
                required_authority="separate source-backed transform evidence",
            )
        )

    elif action_type == "hold" and not valid_hold(shot):
        item = err(
            "invalid hold action",
            shot_id=shot_id,
            motion_type=motion.get("motion_type"),
            motion_family=motion.get("motion_family"),
            cut_priority_score=signals.get("cut_priority_score"),
        )
        if strict:
            errors.append(item)
        else:
            warnings.append(item)

    return errors, warnings


def validate_metadata_against_rules(
    action: Dict[str, Any],
    shot: Dict[str, Any],
    strict_metadata: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    shot_id = int(shot.get("shot_id"))
    action_type = action.get("type")

    if action_type not in PRIMARY_ACTIONS:
        return errors, warnings

    expected = expected_metadata_for_action(str(action_type), shot)

    if action.get("rule_id") != expected["rule_id"]:
        errors.append(
            err(
                "action.rule_id mismatch",
                shot_id=shot_id,
                action_type=action_type,
                rule_id=action.get("rule_id"),
                expected_rule_id=expected["rule_id"],
            )
        )

    if action.get("confidence") != expected["confidence"]:
        item = err(
            "action.confidence mismatch",
            shot_id=shot_id,
            action_type=action_type,
            confidence=action.get("confidence"),
            expected_confidence=expected["confidence"],
        )
        if strict_metadata:
            errors.append(item)
        else:
            warnings.append(item)

    actual_score = action.get("priority_score")
    expected_score = expected["priority_score"]
    if is_number(actual_score) and abs(float(actual_score) - float(expected_score)) > 0.075:
        item = err(
            "action.priority_score differs from deterministic expected score",
            shot_id=shot_id,
            action_type=action_type,
            priority_score=actual_score,
            expected_priority_score=expected_score,
            tolerance=0.075,
        )
        if strict_metadata:
            errors.append(item)
        else:
            warnings.append(item)

    if action.get("intent") != expected["intent"]:
        item = err(
            "action.intent mismatch",
            shot_id=shot_id,
            action_type=action_type,
            intent=action.get("intent"),
            expected_intent=expected["intent"],
        )
        if strict_metadata:
            errors.append(item)
        else:
            warnings.append(item)

    actual_hints = action.get("compiler_hints")
    expected_hints = expected["compiler_hints"]
    if isinstance(actual_hints, dict):
        for key, expected_value in expected_hints.items():
            actual_value = actual_hints.get(key)
            if actual_value != expected_value:
                item = err(
                    "compiler_hints value mismatch",
                    shot_id=shot_id,
                    action_type=action_type,
                    hint_key=key,
                    value=actual_value,
                    expected_value=expected_value,
                )
                if strict_metadata:
                    errors.append(item)
                else:
                    warnings.append(item)

    return errors, warnings


# -------------------------
# Rich compiler contract validation
# -------------------------


def validate_transition_contract(
    shot: Dict[str, Any],
    next_shot: Optional[Dict[str, Any]],
    fps: float,
    strict: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    transition = get_transition_to_next(shot)
    if not transition:
        return errors, warnings

    shot_id = get_int(shot.get("shot_id"), -1)
    confidence = transition.get("confidence")
    transition_type = transition.get("transition_type")

    if transition_type in UNSUPPORTED_EXECUTABLE_TRANSITIONS:
        errors.append(
            err(
                "unsupported executable transition_type",
                shot_id=shot_id,
                transition_type=transition_type,
            )
        )

    if confidence not in {"low", "medium", "high", None}:
        warnings.append(warn("transition confidence is unusual", shot_id=shot_id, confidence=confidence))

    if confidence != "high":
        return errors, warnings

    scores = transition.get("scores")
    reasons = transition.get("reasons")
    observational_candidate = (
        transition_type in OBSERVATIONAL_TRANSITION_CANDIDATES
        and transition.get("editor_actionable") is False
        and transition.get("is_editor_candidate") is not True
        and is_number(transition.get("duration_frames"))
        and float(transition["duration_frames"]) == 0.0
        and is_number(transition.get("duration_seconds"))
        and float(transition["duration_seconds"]) == 0.0
        and isinstance(scores, dict)
        and bool(scores)
        and isinstance(reasons, list)
        and bool(reasons)
    )

    if observational_candidate:
        if transition.get("cut_time") is None and transition.get("cut_frame") is None:
            errors.append(err("high-confidence transition must include cut_time or cut_frame", shot_id=shot_id))
        return errors, warnings

    if not transition_type or "candidate" in str(transition_type).lower():
        errors.append(err("high-confidence transition must have concrete transition_type", shot_id=shot_id, transition_type=transition_type))

    cut_time = transition.get("cut_time")
    cut_frame = transition.get("cut_frame")
    if cut_time is None and cut_frame is None:
        errors.append(err("high-confidence transition must include cut_time or cut_frame", shot_id=shot_id))

    shot_frames = shot_duration_frames(shot, fps)
    next_frames = shot_duration_frames(next_shot, fps) if next_shot else 0
    transition_frames = get_int(transition.get("duration_frames"), DEFAULT_TRANSITION_FRAMES)
    if transition_frames <= 0:
        transition_frames = DEFAULT_TRANSITION_FRAMES

    available_side_frames = min(shot_frames, next_frames) if next_shot else shot_frames
    if transition_frames < MIN_TRANSITION_FRAMES:
        warnings.append(
            warn(
                "transition duration is very short",
                shot_id=shot_id,
                transition_frames=transition_frames,
                min_recommended_frames=MIN_TRANSITION_FRAMES,
            )
        )

    if next_shot is None:
        warnings.append(warn("high-confidence transition exists on final/missing next shot", shot_id=shot_id))
    elif available_side_frames < transition_frames:
        item = err(
            "not enough neighboring shot duration for transition handles",
            shot_id=shot_id,
            transition_frames=transition_frames,
            outgoing_shot_frames=shot_frames,
            incoming_shot_frames=next_frames,
        )
        if strict:
            errors.append(item)
        else:
            warnings.append(item)

    return errors, warnings


def validate_caption_contract(edit_plan: Dict[str, Any], analysis: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    global_style = edit_plan.get("global_style") or {}
    requested_caption_style = global_style.get("caption_style")
    transcript_segments = get_transcript_segments(analysis)
    caption_style_data = get_caption_style_data(analysis)

    report = {
        "requested_caption_style": requested_caption_style,
        "transcript_segments_count": len(transcript_segments),
        "caption_style_present": bool(caption_style_data),
    }

    if requested_caption_style == "detected":
        if not transcript_segments:
            warnings.append(
                warn(
                    "caption_style is detected but no transcript segments were found; subtitle_clips will be empty",
                    requested_caption_style=requested_caption_style,
                )
            )
        if not caption_style_data:
            warnings.append(
                warn(
                    "caption_style is detected but no caption style analysis was found; compiler will use fallback caption style",
                    requested_caption_style=requested_caption_style,
                )
            )

    # Validate segment timing when present. Warnings only, because transcript quality
    # can vary and subtitles are a separate layer.
    bad_segments = []
    for i, segment in enumerate(transcript_segments[:500]):
        start = get_float(segment.get("start"), get_float(segment.get("start_seconds"), -1.0))
        end = get_float(segment.get("end"), get_float(segment.get("end_seconds"), -1.0))
        text = segment.get("text") or segment.get("word") or ""
        if start < 0 or end <= start or not str(text).strip():
            bad_segments.append({"index": i, "start": start, "end": end, "has_text": bool(str(text).strip())})

    if bad_segments:
        warnings.append(warn("some transcript segments have invalid subtitle timing/text", bad_segments=bad_segments[:20], count=len(bad_segments)))

    return errors, warnings, report


def validate_rich_contract(
    edit_plan: Dict[str, Any],
    analysis: Dict[str, Any],
    strict: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    fps = get_fps(analysis)
    analysis_index = build_analysis_index(analysis)

    transition_errors_count = 0
    transition_warnings_count = 0
    for shot_id, shot in sorted(analysis_index.items()):
        next_shot = next_shot_by_id(analysis_index, shot_id)
        t_errors, t_warnings = validate_transition_contract(shot, next_shot, fps, strict=strict)
        transition_errors_count += len(t_errors)
        transition_warnings_count += len(t_warnings)
        errors.extend(t_errors)
        warnings.extend(t_warnings)

    caption_errors, caption_warnings, caption_report = validate_caption_contract(edit_plan, analysis)
    errors.extend(caption_errors)
    warnings.extend(caption_warnings)

    report = {
        "schema_target": "generic_edit_commands_v2_rich_editor_agnostic",
        "fps": fps,
        "analysis_shots_count": len(analysis_index),
        "transition_errors_count": transition_errors_count,
        "transition_warnings_count": transition_warnings_count,
        "caption_contract": caption_report,
        "required_generic_fields": [
            "timeline_start_frame",
            "timeline_end_frame",
            "source_start_frame",
            "source_end_frame",
            "handles",
            "operations.transform_zoom.parameters.keyframes",
            "operations.speed_ramp.parameters.segments",
            "operations.transition_hint.parameters.duration_frames",
            "subtitle_clips",
            "caption_style_resolved",
        ],
    }

    return errors, warnings, report


# -------------------------
# Timeline validation
# -------------------------


def normalize_full_layer_flags(edit_plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove legacy 'handled later' semantics from plan metadata.
    Full layers are carried forward as first-class IR hints.
    """
    if not isinstance(edit_plan, dict):
        return edit_plan

    meta = edit_plan.setdefault("_meta", {})
    if isinstance(meta, dict):
        meta["transitions_handled_later"] = False
        meta["captions_handled_later"] = False
        meta["overlays_handled_later"] = False
        meta["effects_handled_later"] = False
        meta["full_layers_validated"] = True
        meta["rich_generic_contract_target"] = "generic_edit_commands_v2"

    return edit_plan


def validate_timeline(
    edit_plan: Dict[str, Any],
    analysis: Dict[str, Any],
    strict: bool = True,
    strict_metadata: bool = True,
    enforce_expected_action: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    action_counts: Dict[str, int] = {}
    primary_action_counts: Dict[str, int] = {}
    layer_action_counts: Dict[str, int] = {}

    analysis_video_id = analysis.get("job", {}).get("job_id")
    plan_video_id = edit_plan.get("video_id")

    if analysis_video_id and plan_video_id != analysis_video_id:
        errors.append(
            err(
                "video_id mismatch",
                edit_plan_video_id=plan_video_id,
                analysis_video_id=analysis_video_id,
            )
        )

    analysis_shots_by_id = build_analysis_index(analysis)
    expected_ids = set(analysis_shots_by_id.keys())

    timeline = edit_plan.get("timeline", [])
    seen_ids: List[int] = []

    for index, item in enumerate(timeline):
        if not isinstance(item, dict):
            errors.append(err("timeline item must be object", index=index))
            continue

        raw_shot_id = item.get("shot_id")
        if raw_shot_id is None:
            errors.append(err("timeline item missing shot_id", index=index))
            continue

        try:
            shot_id = int(raw_shot_id)
        except Exception:
            errors.append(err("shot_id must be integer", index=index, shot_id=raw_shot_id))
            continue

        seen_ids.append(shot_id)

        source_shot = analysis_shots_by_id.get(shot_id)
        if source_shot is None:
            errors.append(err("unknown shot_id", index=index, shot_id=shot_id))
            continue

        errors.extend(validate_speed_ramp_observation(item, source_shot))
        errors.extend(validate_zoom_observation(item, source_shot))

        actions = item.get("actions")
        if not isinstance(actions, list):
            errors.append(err("actions must be a list", shot_id=shot_id))
            continue

        if len(actions) < 1:
            errors.append(
                err(
                    "at least one action per shot is required",
                    shot_id=shot_id,
                    actions_count=len(actions),
                )
            )
            continue

        primary_actions = [a for a in actions if isinstance(a, dict) and a.get("type") in PRIMARY_ACTIONS]
        if len(primary_actions) != 1:
            errors.append(
                err(
                    "each timeline item must contain exactly one primary action",
                    shot_id=shot_id,
                    primary_actions_count=len(primary_actions),
                    primary_action_types=[a.get("type") for a in primary_actions if isinstance(a, dict)],
                )
            )

        first_action = actions[0] if actions else None
        if not isinstance(first_action, dict) or first_action.get("type") not in PRIMARY_ACTIONS:
            errors.append(
                err(
                    "actions[0] must be the primary action used by compile_generic_edit",
                    shot_id=shot_id,
                    first_action_type=first_action.get("type") if isinstance(first_action, dict) else None,
                )
            )

        for action_index, action in enumerate(actions):
            action_type = action.get("type") if isinstance(action, dict) else None
            if action_type:
                action_counts[action_type] = action_counts.get(action_type, 0) + 1
                if action_type in PRIMARY_ACTIONS:
                    primary_action_counts[action_type] = primary_action_counts.get(action_type, 0) + 1
                elif action_type in LAYER_ACTIONS:
                    layer_action_counts[action_type] = layer_action_counts.get(action_type, 0) + 1

            shape_errors, shape_warnings = validate_action_shape(
                action=action,
                shot_id=shot_id,
                action_index=action_index,
                is_primary_position=(action_index == 0),
            )
            errors.extend(shape_errors)
            warnings.extend(shape_warnings)

        if primary_actions:
            primary_action = primary_actions[0]
            primary_shape_errors, _ = validate_action_shape(primary_action, shot_id, 0)
            if not primary_shape_errors:
                rule_errors, rule_warnings = validate_action_against_analysis(
                    action=primary_action,
                    shot=source_shot,
                    strict=strict,
                    enforce_expected_action=enforce_expected_action,
                )
                errors.extend(rule_errors)
                warnings.extend(rule_warnings)

                metadata_errors, metadata_warnings = validate_metadata_against_rules(
                    action=primary_action,
                    shot=source_shot,
                    strict_metadata=strict_metadata,
                )
                errors.extend(metadata_errors)
                warnings.extend(metadata_warnings)

    seen_set = set(seen_ids)
    missing_ids = sorted(expected_ids - seen_set)
    unknown_ids = sorted(seen_set - expected_ids)
    duplicate_ids = sorted({x for x in seen_ids if seen_ids.count(x) > 1})

    if missing_ids:
        errors.append(err("missing shots from edit_plan", missing_shot_ids=missing_ids))

    if unknown_ids:
        errors.append(err("edit_plan contains unknown shots", unknown_shot_ids=unknown_ids))

    if duplicate_ids:
        errors.append(err("duplicate shot_ids in edit_plan", duplicate_shot_ids=duplicate_ids))

    if len(timeline) != len(expected_ids):
        errors.append(
            err(
                "timeline length mismatch",
                timeline_count=len(timeline),
                expected_shot_count=len(expected_ids),
            )
        )

    stats = {
        "timeline_count": len(timeline) if isinstance(timeline, list) else 0,
        "expected_shot_count": len(expected_ids),
        "action_counts": action_counts,
        "primary_action_counts": primary_action_counts,
        "layer_action_counts": layer_action_counts,
    }

    return errors, warnings, stats


# -------------------------
# Output
# -------------------------


def build_validated_output(
    edit_plan: Dict[str, Any],
    analysis: Dict[str, Any],
    errors: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
    strict: bool,
    strict_metadata: bool,
    enforce_expected_action: bool,
    validate_rich: bool,
    analysis_contract: Dict[str, Any],
    timeline_stats: Dict[str, Any],
    rich_contract: Dict[str, Any],
) -> Dict[str, Any]:
    success = len(errors) == 0

    return {
        "success": success,
        "validation_version": VERSION,
        "strict": strict,
        "strict_metadata": strict_metadata,
        "enforce_expected_action": enforce_expected_action,
        "validate_rich_contract": validate_rich,
        "video_id": edit_plan.get("video_id") if isinstance(edit_plan, dict) else None,
        "analysis_video_id": analysis.get("job", {}).get("job_id") if isinstance(analysis, dict) else None,
        "errors_count": len(errors),
        "warnings_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "analysis_contract": analysis_contract,
        "timeline_stats": timeline_stats,
        "rich_generic_contract": rich_contract,
        "edit_plan": edit_plan,
        "_meta": {
            "validated_at_unix": round(time.time(), 3),
            "allowed_actions": sorted(ALLOWED_ACTIONS),
            "primary_actions": sorted(PRIMARY_ACTIONS),
            "layer_actions": sorted(LAYER_ACTIONS),
            "disallowed_actions": sorted(DISALLOWED_ACTIONS),
            "required_primary_action_fields": sorted(REQUIRED_PRIMARY_ACTION_FIELDS),
            "required_primary_compiler_hint_keys": sorted(REQUIRED_PRIMARY_COMPILER_HINT_KEYS),
            "full_layers_validated": True,
            "transitions_handled_later": False,
            "captions_handled_later": False,
            "overlays_handled_later": False,
            "effects_handled_later": False,
            "rich_generic_contract_target": "generic_edit_commands_v2",
            "ready_for_compile_generic_edit_v2": success,
        },
    }


# -------------------------
# CLI
# -------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate editor-agnostic edit_plan.json against analysis.json")

    parser.add_argument("--analysis", required=True, help="Path to analysis.json")
    parser.add_argument("--edit-plan", required=True, help="Path to edit_plan.json")
    parser.add_argument("--output", required=True, help="Path to validated_edit_plan.json")

    parser.add_argument("--strict", default="true", choices=["true", "false"])
    parser.add_argument("--strict-metadata", default="true", choices=["true", "false"])
    parser.add_argument("--enforce-expected-action", default="true", choices=["true", "false"])
    parser.add_argument(
        "--validate-rich-contract",
        default="true",
        choices=["true", "false"],
        help="Validate analysis/edit-plan readiness for compile_generic_edit.py v2 rich generic commands.",
    )

    args = parser.parse_args()

    strict = args.strict.lower() == "true"
    strict_metadata = args.strict_metadata.lower() == "true"
    enforce_expected_action = args.enforce_expected_action.lower() == "true"
    validate_rich_contract_enabled = args.validate_rich_contract.lower() == "true"

    analysis = load_json(args.analysis)
    edit_plan = normalize_full_layer_flags(load_json(args.edit_plan))

    structure_errors, structure_warnings = validate_structure(edit_plan)
    analysis_errors, analysis_warnings, analysis_contract = validate_analysis_contract(analysis, strict=strict)

    errors = structure_errors + analysis_errors
    warnings = structure_warnings + analysis_warnings
    timeline_stats: Dict[str, Any] = {}
    rich_contract: Dict[str, Any] = {}

    if not structure_errors and not analysis_errors:
        timeline_errors, timeline_warnings, timeline_stats = validate_timeline(
            edit_plan=edit_plan,
            analysis=analysis,
            strict=strict,
            strict_metadata=strict_metadata,
            enforce_expected_action=enforce_expected_action,
        )
        errors.extend(timeline_errors)
        warnings.extend(timeline_warnings)

        if validate_rich_contract_enabled:
            rich_errors, rich_warnings, rich_contract = validate_rich_contract(
                edit_plan=edit_plan,
                analysis=analysis,
                strict=strict,
            )
            errors.extend(rich_errors)
            warnings.extend(rich_warnings)
    else:
        timeline_stats = {}
        rich_contract = {"skipped": True, "reason": "structure_or_analysis_contract_errors"}

    validated = build_validated_output(
        edit_plan=edit_plan,
        analysis=analysis,
        errors=errors,
        warnings=warnings,
        strict=strict,
        strict_metadata=strict_metadata,
        enforce_expected_action=enforce_expected_action,
        validate_rich=validate_rich_contract_enabled,
        analysis_contract=analysis_contract,
        timeline_stats=timeline_stats,
        rich_contract=rich_contract,
    )

    save_json(args.output, validated)

    print(json.dumps({
        "ok": validated["success"],
        "output": os.path.abspath(args.output),
        "errors_count": validated["errors_count"],
        "warnings_count": validated["warnings_count"],
        "video_id": validated["video_id"],
        "validation_version": VERSION,
        "ready_for_compile_generic_edit_v2": validated["_meta"]["ready_for_compile_generic_edit_v2"],
        "timeline_stats": validated.get("timeline_stats", {}),
    }, indent=2), flush=True)

    if not validated["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
