import argparse
import json
import re
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION = "edit_planner_v4_2_zoom_candidate_non_actionable"

# Primary editor-agnostic intent actions. These are still not DaVinci/OpenReel commands.
# The compiler converts their deterministic operation_hints into generic edit commands.
ALLOWED_ACTIONS = [
    "hold",
    "cut",
    "beat_cut",
]

VALID_SPEED_RAMP_INTENSITIES = {"medium", "high", "very_high"}
VALID_PACE = {"slow", "medium", "fast"}
VALID_CAPTION_STYLE = {"detected", "none", "manual"}
VALID_CAPTION_DENSITY = {"low", "medium", "high"}
VALID_CAPTION_PLACEMENT = {
    "bottom_center",
    "middle_center",
    "top_center",
    "lower_third",
}


# -------------------------
# IO / primitives
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


def safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def boolish(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


# -------------------------
# Analysis extraction
# -------------------------


def get_analysis_shots(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    return safe_list(safe_dict(analysis.get("timeline")).get("shots"))


def analysis_fps(analysis: Dict[str, Any]) -> float:
    fps = get_float(safe_dict(analysis.get("job")).get("fps"), 0.0)
    if fps <= 0:
        fps = get_float(safe_dict(analysis.get("source")).get("fps"), 0.0)
    return fps if fps > 0 else 24.0


def shot_start_frame(shot: Dict[str, Any], fps: float) -> int:
    if shot.get("start_frame") is not None:
        return get_int(shot.get("start_frame"), 0)
    return max(0, int(round(get_float(shot.get("start_seconds"), 0.0) * fps)))


def shot_end_frame(shot: Dict[str, Any], fps: float) -> int:
    if shot.get("end_frame") is not None:
        return get_int(shot.get("end_frame"), shot_start_frame(shot, fps) + 1)
    return max(shot_start_frame(shot, fps) + 1, int(round(get_float(shot.get("end_seconds"), 0.0) * fps)))


def shot_duration_frames(shot: Dict[str, Any], fps: float) -> int:
    start = shot_start_frame(shot, fps)
    end = shot_end_frame(shot, fps)
    if end > start:
        return max(1, end - start)
    return max(1, int(round(get_float(shot.get("duration_seconds"), 0.0) * fps)))


def extract_transcript_summary(analysis: Dict[str, Any]) -> Dict[str, Any]:
    transcript = safe_dict(analysis.get("transcript"))
    candidates = [
        safe_list(transcript.get("segments")),
        safe_list(transcript.get("transcript_segments")),
        safe_list(safe_dict(analysis.get("timeline")).get("transcript_segments")),
        safe_list(safe_dict(analysis.get("captions")).get("segments")),
    ]
    segments: List[Any] = []
    for candidate in candidates:
        if candidate:
            segments = candidate
            break

    words_count = 0
    for seg in segments:
        seg_d = safe_dict(seg)
        if isinstance(seg_d.get("words"), list):
            words_count += len(seg_d.get("words") or [])
        elif isinstance(seg_d.get("text"), str):
            words_count += len(seg_d.get("text", "").split())

    return {
        "available": bool(segments),
        "segments_count": len(segments),
        "words_count_estimate": words_count,
    }


def extract_caption_style_summary(analysis: Dict[str, Any]) -> Dict[str, Any]:
    caption_style = analysis.get("caption_style")
    if not isinstance(caption_style, dict):
        caption_style = safe_dict(safe_dict(analysis.get("style")).get("caption_style"))

    subtitle_summary = safe_dict(caption_style.get("summary"))
    if not subtitle_summary:
        subtitle_summary = safe_dict(caption_style.get("subtitle_style_summary"))

    groups = caption_style.get("groups")
    if not isinstance(groups, list):
        groups = caption_style.get("subtitle_groups")
    groups = groups if isinstance(groups, list) else []

    return {
        "available": bool(caption_style),
        "summary_keys": sorted(list(subtitle_summary.keys()))[:30] if isinstance(subtitle_summary, dict) else [],
        "groups_count": len(groups),
    }


def choose_caption_density(duration_seconds: float, transcript_summary: Dict[str, Any]) -> str:
    if not transcript_summary.get("available"):
        return "low"
    words = get_int(transcript_summary.get("words_count_estimate"), 0)
    if duration_seconds <= 0:
        return "medium"
    wps = words / max(1.0, duration_seconds)
    if wps >= 3.0:
        return "high"
    if wps <= 1.2:
        return "low"
    return "medium"


def build_caption_plan(analysis: Dict[str, Any]) -> Dict[str, Any]:
    duration = get_float(safe_dict(analysis.get("summary")).get("duration_seconds"), 0.0)
    transcript_summary = extract_transcript_summary(analysis)
    caption_style_summary = extract_caption_style_summary(analysis)
    enabled = bool(transcript_summary.get("available"))
    style_source = "detected" if caption_style_summary.get("available") else ("none" if not enabled else "manual")

    return {
        "enabled": enabled,
        "style_source": style_source,
        "placement": "bottom_center",
        "density": choose_caption_density(duration, transcript_summary),
        "source": "transcript" if enabled else "none",
        "max_chars_per_caption": 42 if enabled else 0,
        "max_lines": 2 if enabled else 0,
        "transcript": transcript_summary,
        "caption_style": caption_style_summary,
    }


def slim_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    fps = analysis_fps(analysis)
    shots = []

    for shot in get_analysis_shots(analysis):
        edit_signals = safe_dict(shot.get("edit_signals"))
        motion = safe_dict(shot.get("motion"))
        start_f = shot_start_frame(shot, fps)
        end_f = shot_end_frame(shot, fps)
        duration_f = max(1, end_f - start_f)

        transition_to_next = shot.get("transition_to_next")
        transition_hint = None
        if isinstance(transition_to_next, dict):
            transition_hint = {
                "transition_type": transition_to_next.get("transition_type"),
                "confidence": transition_to_next.get("confidence"),
                "cut_time": transition_to_next.get("cut_time"),
                "cut_frame": transition_to_next.get("cut_frame"),
            }

        shots.append({
            "shot_id": shot.get("shot_id"),
            "start": get_float(shot.get("start_seconds"), start_f / fps),
            "end": get_float(shot.get("end_seconds"), end_f / fps),
            "duration": get_float(shot.get("duration_seconds"), duration_f / fps),
            "start_frame": start_f,
            "end_frame": end_f,
            "duration_frames": duration_f,
            "motion_type": motion.get("motion_type"),
            "motion_family": motion.get("motion_family"),
            "motion_intensity": motion.get("motion_intensity"),
            "motion_confidence": motion.get("confidence"),
            "speed_ramp_candidate": edit_signals.get("speed_ramp_candidate"),
            "zoom_candidate": bool(motion.get("zoom_candidate")),
            "zoom_direction": motion.get("zoom_direction"),
            "zoom_confidence": safe_dict(motion.get("motion_based_zoom")).get("confidence"),
            "zoom_affine_scale_delta": safe_dict(motion.get("camera_motion")).get("avg_scale_delta"),
            "cut_rhythm_label": edit_signals.get("cut_rhythm_label"),
            "cut_priority_score": edit_signals.get("cut_priority_score"),
            "beats_in_shot_count": edit_signals.get("beats_in_shot_count"),
            "downbeats_in_shot_count": edit_signals.get("downbeats_in_shot_count"),
            "nearest_beat_to_start": safe_dict(edit_signals.get("nearest_beat_to_start")).get("time"),
            "nearest_beat_to_end": safe_dict(edit_signals.get("nearest_beat_to_end")).get("time"),
            "transition_to_next": transition_hint,
        })

    summary = safe_dict(analysis.get("summary"))
    job = safe_dict(analysis.get("job"))
    return {
        "video_id": job.get("job_id"),
        "duration_seconds": summary.get("duration_seconds"),
        "fps": fps,
        "bpm": summary.get("bpm"),
        "rhythm_confidence": summary.get("rhythm_confidence"),
        "shot_count": summary.get("shot_count", len(shots)),
        "motion_summary": summary.get("motion_summary", {}),
        "caption_plan": build_caption_plan(analysis),
        "transition_policy": {
            "source": "analysis.transition_to_next",
            "planner_should_not_invent_transitions": True,
            "compiler_will_resolve_duration_and_handles": True,
        },
        "shots": shots,
    }


# -------------------------
# Prompt
# -------------------------


def build_prompt(slim: Dict[str, Any]) -> str:
    """
    The LLM may propose the high-level action, but this script still rebuilds
    deterministic metadata and operation hints after the LLM response. That keeps
    the planner useful without allowing hallucinated editor-specific commands.
    """
    action_schema = {
        "type": "hold|cut|beat_cut",
        "reason": "short practical reason",
        "caption_policy": "none|keep|emphasize_speech",
        "operation_hints": [
            {
                "operation": "cut|hold|beat_cut",
            }
        ],
    }

    return f"""
You are an editor-agnostic video edit planner.

Your job:
Create edit_plan.json with executable editor-agnostic intent hints.
Do NOT create DaVinci commands.
Do NOT create OpenReel commands.
Do NOT use software-specific API names.

Allowed primary actions:
{json.dumps(ALLOWED_ACTIONS)}

Forbidden primary actions:
["transition", "subtitle_focus", "camera_move", "effect", "text", "overlay"]

Required JSON schema:
{{
  "version": "1.0",
  "video_id": "string",
  "global_style": {{
    "pace": "slow|medium|fast",
    "music_sync": true,
    "caption_style": "detected|none|manual"
  }},
  "caption_plan": {{
    "enabled": true,
    "style_source": "detected|none|manual",
    "placement": "bottom_center|middle_center|top_center|lower_third",
    "density": "low|medium|high"
  }},
  "timeline": [
    {{
      "shot_id": 1,
      "actions": [
        {json.dumps(action_schema, ensure_ascii=False)}
      ]
    }}
  ]
}}

Hard rules:
- Return ONLY valid JSON.
- Follow the required schema exactly.
- Every shot from the input must appear exactly once.
- Do not invent shot IDs.
- Maximum 1 primary action per shot.
- Choose the strongest valid action only.
- Prefer cut or hold when uncertain.
- Do NOT output transition actions. Transition duration, side, placement, and handles are resolved later from analysis.json by the generic compiler.
- Do NOT invent subtitle text. Only decide caption_plan enabled/style/placement/density.

Action priority:
1. beat_cut
2. cut
3. hold

Decision rules:
- Treat speed_ramp_candidate as non-actionable motion metadata only. Never emit speed_ramp without separate source-backed retime authority.
- Treat affine-scale zoom_candidate motion as non-actionable metadata only. Never emit zoom_in/zoom_out without separate source-backed editable-transform authority.
- Use beat_cut only when cut_priority_score > 0.5 AND beats_in_shot_count > 0.
- Use cut for non-actionable speed/zoom candidates and when cut_priority_score >= 0.3.
- Use hold only when no higher-priority action applies AND motion_family is static AND cut_priority_score < 0.3.
- If none apply, use cut.

Operation hint rules:
- Emit only source-preserving cut/hold/beat_cut hints from this planner.
- If unsure about exact values, output a valid simple action; sanitizer will rebuild deterministic hints.

Caption plan rules:
- If transcript is available, captions should usually be enabled.
- Use style_source detected when caption style analysis exists.
- Default placement is bottom_center.
- Density should follow speech amount: low, medium, high.

Reason rules:
- Reasons must reference only fields from the provided analysis.
- Do not mention transitions in reasons.
- Do not say "high confidence" unless an exact provided confidence field says "high".
- Keep reasons short and practical.

Analysis:
{json.dumps(slim, ensure_ascii=False)}
"""


# -------------------------
# Ollama / JSON parsing
# -------------------------


def call_ollama(prompt: str, model: str, url: str) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_ctx": 12288,
        },
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(req, timeout=180) as response:
        data = json.loads(response.read().decode("utf-8"))

    return data["response"]


def extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()

    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in LLM response.")

    return json.loads(match.group(0))


# -------------------------
# Deterministic action logic
# -------------------------


def shot_supports_push_in(shot: Dict[str, Any]) -> bool:
    motion_type = str(shot.get("motion_type") or "").lower()
    motion_family = str(shot.get("motion_family") or "").lower()
    return motion_family == "push_in" or "push_in" in motion_type


def shot_supports_pull_out(shot: Dict[str, Any]) -> bool:
    motion_type = str(shot.get("motion_type") or "").lower()
    motion_family = str(shot.get("motion_family") or "").lower()
    return motion_family == "pull_out" or "pull_out" in motion_type


def strength_to_zoom_scale(strength: str) -> float:
    if strength == "strong":
        return 1.18
    if strength == "medium":
        return 1.12
    return 1.06


def strength_to_speed_multiplier(strength: str) -> float:
    if strength == "strong":
        return 1.45
    if strength == "medium":
        return 1.25
    if strength == "subtle":
        return 1.12
    return 1.2


def build_zoom_operation_hint(action_type: str, shot: Dict[str, Any], compiler_hints: Dict[str, Any]) -> Dict[str, Any]:
    duration_frames = max(2, get_int(shot.get("duration_frames"), 2))
    last = max(1, duration_frames - 1)
    strength = str(compiler_hints.get("strength") or "subtle")
    scale = strength_to_zoom_scale(strength)
    direction = "in" if action_type == "zoom_in" else "out"
    if direction == "in":
        start_zoom, end_zoom = 1.0, scale
    else:
        start_zoom, end_zoom = scale, 1.0

    return {
        "operation": "transform_zoom",
        "description": f"Editor-agnostic keyframed zoom {direction}.",
        "parameters": {
            "direction": direction,
            "start_scale": round(start_zoom, 4),
            "end_scale": round(end_zoom, 4),
            "easing": "ease_in_out",
            "preferred_timing": "full_shot",
        },
        "keyframes": [
            {"relative_frame": 0, "zoom": round(start_zoom, 4), "scale": round(start_zoom, 4)},
            {"relative_frame": last, "zoom": round(end_zoom, 4), "scale": round(end_zoom, 4)},
        ],
    }


def split_duration_into_ramp_segments(duration_frames: int) -> Tuple[int, int, int, int]:
    duration_frames = max(3, duration_frames)
    ramp_in = max(1, int(round(duration_frames * 0.25)))
    ramp_out = max(1, int(round(duration_frames * 0.25)))
    hold = max(1, duration_frames - ramp_in - ramp_out)
    # Ensure exact coverage.
    if ramp_in + hold + ramp_out > duration_frames:
        hold = max(1, duration_frames - ramp_in - ramp_out)
    f0 = 0
    f1 = min(duration_frames, f0 + ramp_in)
    f2 = min(duration_frames, f1 + hold)
    f3 = duration_frames
    if f2 <= f1:
        f2 = min(duration_frames, f1 + 1)
    if f3 <= f2:
        f3 = f2 + 1
    return f0, f1, f2, f3


def build_speed_ramp_operation_hint(shot: Dict[str, Any], compiler_hints: Dict[str, Any]) -> Dict[str, Any]:
    duration_frames = max(3, get_int(shot.get("duration_frames"), 3))
    strength = str(compiler_hints.get("strength") or "medium")
    multiplier = strength_to_speed_multiplier(strength)
    f0, f1, f2, f3 = split_duration_into_ramp_segments(duration_frames)

    return {
        "operation": "speed_ramp",
        "description": "Editor-agnostic speed ramp segment plan.",
        "parameters": {
            "style": compiler_hints.get("ramp_style", "smooth"),
            "speed_multiplier": round(multiplier, 4),
            "ramp_in_percent": 0.25,
            "hold_percent": 0.5,
            "ramp_out_percent": 0.25,
            "sync_to_beat": bool(compiler_hints.get("sync_to_beat", False)),
            "preferred_timing": "within_shot",
        },
        "segments": [
            {
                "label": "ramp_in",
                "from_frame": f0,
                "to_frame": f1,
                "start_speed": 1.0,
                "end_speed": round(multiplier, 4),
                "speed": round(multiplier, 4),
            },
            {
                "label": "hold_fast",
                "from_frame": f1,
                "to_frame": f2,
                "start_speed": round(multiplier, 4),
                "end_speed": round(multiplier, 4),
                "speed": round(multiplier, 4),
            },
            {
                "label": "ramp_out",
                "from_frame": f2,
                "to_frame": f3,
                "start_speed": round(multiplier, 4),
                "end_speed": 1.0,
                "speed": 1.0,
            },
        ],
    }


def build_cut_operation_hint(action_type: str, shot: Dict[str, Any], compiler_hints: Dict[str, Any]) -> Dict[str, Any]:
    op_name = "beat_cut" if action_type == "beat_cut" else ("hold" if action_type == "hold" else "cut")
    params: Dict[str, Any] = {
        "preferred_timing": compiler_hints.get("preferred_timing", "shot_boundary"),
        "sync_to_beat": bool(compiler_hints.get("sync_to_beat", False)),
    }
    if action_type == "beat_cut":
        params["nearest_beat_to_start"] = shot.get("nearest_beat_to_start")
        params["nearest_beat_to_end"] = shot.get("nearest_beat_to_end")
        params["prefer_downbeat"] = bool(compiler_hints.get("prefer_downbeat", False))
    if action_type == "hold":
        params["preserve_duration"] = True
    return {
        "operation": op_name,
        "description": f"Editor-agnostic {op_name} instruction.",
        "parameters": params,
    }


def build_operation_hints(action_type: str, shot: Dict[str, Any], compiler_hints: Dict[str, Any]) -> List[Dict[str, Any]]:
    if action_type in {"zoom_in", "zoom_out"}:
        raise RuntimeError(
            "zoom action is not executable: current planner has no source-backed editable zoom authority contract"
        )
    if action_type == "speed_ramp":
        return [build_speed_ramp_operation_hint(shot, compiler_hints)]
    return [build_cut_operation_hint(action_type, shot, compiler_hints)]


def compute_action_metadata(action_type: str, shot: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic metadata for compiler layers.
    This is editor-agnostic: no OpenReel, no DaVinci-specific values.
    """
    motion_intensity = str(shot.get("motion_intensity") or "").lower()
    motion_confidence = str(shot.get("motion_confidence") or "").lower()
    cut_priority_score = get_float(shot.get("cut_priority_score"), 0.0)
    beats = get_int(shot.get("beats_in_shot_count"), 0)
    downbeats = get_int(shot.get("downbeats_in_shot_count"), 0)

    rule_id = "R_FALLBACK_CUT"
    confidence = "medium"
    priority_score = 0.35
    intent = "safe_cut"
    compiler_hints: Dict[str, Any] = {
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
        "operation_hints": build_operation_hints(action_type, shot, compiler_hints),
    }


def build_speed_ramp_observation(shot: Dict[str, Any]) -> Dict[str, Any]:
    """Preserve motion-derived speed interest without granting retime authority."""
    candidate = bool(shot.get("speed_ramp_candidate"))
    return {
        "candidate": candidate,
        "actionable": False,
        "authority": "motion_heuristic_only",
        "motion_intensity": shot.get("motion_intensity"),
        "motion_confidence": shot.get("motion_confidence"),
        "reason": (
            "motion analysis marked a speed-ramp candidate; exact retime authority "
            "requires separate source-backed evidence"
            if candidate
            else "motion analysis did not mark a speed-ramp candidate"
        ),
    }


def build_zoom_observation(shot: Dict[str, Any]) -> Dict[str, Any]:
    """Preserve affine-scale motion evidence without granting editable zoom authority."""
    candidate = bool(shot.get("zoom_candidate"))
    return {
        "candidate": candidate,
        "actionable": False,
        "authority": "motion_heuristic_only",
        "source": "motion_affine_scale_delta",
        "direction": shot.get("zoom_direction") if candidate else None,
        "confidence": shot.get("zoom_confidence"),
        "motion_family": shot.get("motion_family"),
        "motion_type": shot.get("motion_type"),
        "motion_intensity": shot.get("motion_intensity"),
        "avg_scale_delta": shot.get("zoom_affine_scale_delta"),
        "reason": (
            "affine scale motion marked a zoom candidate; editable zoom authority "
            "requires separate source-backed transform evidence"
            if candidate
            else "affine scale motion did not mark a zoom candidate"
        ),
    }


def expected_action_for_shot(shot: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic fallback/sanitizer using priority rules.
    This keeps the planner output safe even when the local LLM ignores rules.
    """
    motion_type = str(shot.get("motion_type") or "")
    motion_family = str(shot.get("motion_family") or "")
    motion_intensity = str(shot.get("motion_intensity") or "")
    cut_priority_score = get_float(shot.get("cut_priority_score"), 0.0)
    beats_in_shot_count = get_float(shot.get("beats_in_shot_count"), 0.0)
    speed_ramp_candidate = bool(shot.get("speed_ramp_candidate"))
    zoom_candidate = bool(shot.get("zoom_candidate"))

    if speed_ramp_candidate and motion_intensity in VALID_SPEED_RAMP_INTENSITIES:
        action_type = "cut"
        reason = "speed_ramp_candidate retained as non-actionable motion observation; preserve source timing"

    elif cut_priority_score > 0.5 and beats_in_shot_count > 0:
        action_type = "beat_cut"
        reason = f"cut_priority_score is {round(cut_priority_score, 4)} and beats_in_shot_count is {int(beats_in_shot_count)}"

    elif zoom_candidate:
        action_type = "cut"
        reason = "zoom_candidate retained as non-actionable motion observation; preserve source geometry"

    elif cut_priority_score >= 0.3:
        action_type = "cut"
        reason = f"cut_priority_score is {round(cut_priority_score, 4)}"

    elif motion_family == "static" and cut_priority_score < 0.3:
        action_type = "hold"
        reason = f"motion_family is static and cut_priority_score is {round(cut_priority_score, 4)}"

    else:
        action_type = "cut"
        reason = "fallback because no higher-priority action applies"

    metadata = compute_action_metadata(action_type, shot)

    return {
        "type": action_type,
        "reason": reason,
        **metadata,
    }


def normalize_action_reason(reason: Any, fallback: str) -> str:
    reason = str(reason or fallback).strip()
    forbidden = ["transition", "subtitle", "caption text", "davinci", "openreel"]
    if any(term in reason.lower() for term in forbidden):
        reason = fallback
    return reason[:180]


def sanitize_caption_plan(raw_plan: Dict[str, Any], slim: Dict[str, Any]) -> Dict[str, Any]:
    source = slim.get("caption_plan") or {}
    raw = safe_dict(raw_plan.get("caption_plan"))
    enabled_default = bool(source.get("enabled", False))

    enabled = boolish(raw.get("enabled"), enabled_default)
    style_source = raw.get("style_source") if raw.get("style_source") in VALID_CAPTION_STYLE else source.get("style_source", "detected")
    if not enabled:
        style_source = "none"
    placement = raw.get("placement") if raw.get("placement") in VALID_CAPTION_PLACEMENT else source.get("placement", "bottom_center")
    density = raw.get("density") if raw.get("density") in VALID_CAPTION_DENSITY else source.get("density", "medium")

    return {
        "enabled": enabled,
        "style_source": style_source,
        "placement": placement,
        "density": density,
        "source": source.get("source", "transcript" if enabled else "none"),
        "max_chars_per_caption": get_int(source.get("max_chars_per_caption"), 42 if enabled else 0),
        "max_lines": get_int(source.get("max_lines"), 2 if enabled else 0),
        "notes": "Planner only decides caption policy. Text/timestamps come from transcript.",
    }


def sanitize_global_style(raw_style: Dict[str, Any], caption_plan: Dict[str, Any]) -> Dict[str, Any]:
    pace = raw_style.get("pace") if raw_style.get("pace") in VALID_PACE else "medium"
    music_sync = boolish(raw_style.get("music_sync"), True)
    if not caption_plan.get("enabled"):
        caption_style = "none"
    else:
        caption_style = raw_style.get("caption_style") if raw_style.get("caption_style") in VALID_CAPTION_STYLE else caption_plan.get("style_source", "detected")
        if caption_style == "none" and caption_plan.get("enabled"):
            caption_style = caption_plan.get("style_source", "detected") or "detected"
    return {
        "pace": pace,
        "music_sync": music_sync,
        "caption_style": caption_style,
    }


def sanitize_edit_plan(edit_plan: Dict[str, Any], slim: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Makes the output schema-safe and removes forbidden/hallucinated actions.
    This is not a replacement for validate_edit_plan.py; it is a pre-cleaning layer.

    v4 also rebuilds deterministic operation_hints. The LLM can suggest them, but
    the sanitized plan always contains safe, frame-valid rich hints.
    """
    shots = safe_list(slim.get("shots"))
    shot_by_id = {int(s["shot_id"]): s for s in shots if s.get("shot_id") is not None}

    timeline_by_id: Dict[int, Dict[str, Any]] = {}
    for item in safe_list(edit_plan.get("timeline")):
        item_d = safe_dict(item)
        try:
            shot_id = int(item_d.get("shot_id"))
        except Exception:
            continue
        if shot_id in shot_by_id and shot_id not in timeline_by_id:
            timeline_by_id[shot_id] = item_d

    cleaned_timeline = []
    corrections: List[Dict[str, Any]] = []

    for shot in shots:
        shot_id = int(shot["shot_id"])
        item = timeline_by_id.get(shot_id, {})
        actions = safe_list(item.get("actions"))
        action = safe_dict(actions[0]) if actions and isinstance(actions[0], dict) else None

        expected = expected_action_for_shot(shot)

        if not action or action.get("type") not in ALLOWED_ACTIONS:
            corrections.append({
                "shot_id": shot_id,
                "reason": "missing_or_forbidden_action_replaced",
                "replacement": expected["type"],
            })
            action = expected

        elif action.get("type") != expected["type"]:
            corrections.append({
                "shot_id": shot_id,
                "reason": "action_replaced_by_deterministic_priority_rules",
                "llm_action": action.get("type"),
                "replacement": expected["type"],
            })
            action = expected

        else:
            reason = normalize_action_reason(action.get("reason"), expected["reason"])
            metadata = compute_action_metadata(action["type"], shot)
            action = {
                "type": action["type"],
                "reason": reason,
                **metadata,
            }

        # Caption policy is allowed as metadata on the primary action, but never as
        # a separate primary action that would break the one-action-per-shot rule.
        action["caption_policy"] = "emphasize_speech" if action["type"] in {"beat_cut", "speed_ramp"} else "keep"

        cleaned_timeline.append({
            "shot_id": shot_id,
            "actions": [action],
            "observations": {
                "speed_ramp_candidate": build_speed_ramp_observation(shot),
                "zoom_candidate": build_zoom_observation(shot),
            },
        })

    caption_plan = sanitize_caption_plan(edit_plan, slim)
    global_style = sanitize_global_style(safe_dict(edit_plan.get("global_style")), caption_plan)

    cleaned = {
        "version": "1.0",
        "video_id": slim.get("video_id"),
        "global_style": global_style,
        "caption_plan": caption_plan,
        "transition_policy": {
            "source": "analysis.transition_to_next",
            "planner_invents_transitions": False,
            "compiler_resolves_duration_side_placement_handles": True,
        },
        "timeline": cleaned_timeline,
    }

    return cleaned, corrections


# -------------------------
# Main
# -------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan editor-agnostic edit intent with rich operation hints.")
    parser.add_argument("--analysis", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="llama3.1")
    parser.add_argument("--ollama-url", default="http://localhost:11434/api/generate")
    parser.add_argument("--no-sanitize", action="store_true", help="Save raw LLM output without deterministic pre-cleaning. Not recommended.")
    parser.add_argument("--skip-llm", action="store_true", help="Use deterministic planner only. Useful when Ollama is unavailable.")
    args = parser.parse_args()

    analysis = load_json(args.analysis)
    slim = slim_analysis(analysis)

    raw = ""
    edit_plan: Dict[str, Any]

    if args.skip_llm:
        edit_plan = {
            "version": "1.0",
            "video_id": slim.get("video_id"),
            "global_style": {
                "pace": "medium",
                "music_sync": True,
                "caption_style": "detected" if safe_dict(slim.get("caption_plan")).get("enabled") else "none",
            },
            "caption_plan": slim.get("caption_plan") or {},
            "timeline": [],
        }
    else:
        prompt = build_prompt(slim)
        raw = call_ollama(prompt, args.model, args.ollama_url)
        edit_plan = extract_json(raw)

    corrections: List[Dict[str, Any]] = []
    if not args.no_sanitize:
        edit_plan, corrections = sanitize_edit_plan(edit_plan, slim)

    edit_plan["_meta"] = {
        "planner_version": VERSION,
        "model": args.model,
        "source_analysis": args.analysis,
        "allowed_actions": ALLOWED_ACTIONS,
        "transitions_handled_later": False,
        "transition_policy": "analysis_driven_compiler_resolved",
        "captions_handled_later": False,
        "caption_policy_included": True,
        "rich_operation_hints": True,
        "sanitized": not args.no_sanitize,
        "deterministic_metadata": True,
        "deterministic_operation_hints": not args.no_sanitize,
        "skip_llm": bool(args.skip_llm),
        "corrections_count": len(corrections),
        "corrections": corrections[:50],
    }

    save_json(args.output, edit_plan)

    print(json.dumps({
        "ok": True,
        "planner_version": VERSION,
        "output": args.output,
        "video_id": edit_plan.get("video_id"),
        "shots_planned": len(edit_plan.get("timeline", [])),
        "caption_plan_enabled": safe_dict(edit_plan.get("caption_plan")).get("enabled"),
        "sanitized": not args.no_sanitize,
        "rich_operation_hints": True,
        "deterministic_metadata": True,
        "corrections_count": len(corrections),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
