import argparse
import json
import os
import sys
import time
from pathlib import Path
from statistics import mean


VERSION = "merge_analysis_v2_2_caption_foreground_assets_ready"


# -------------------------
# IO
# -------------------------

def load_json(path, required=True, default=None):
    if not path:
        if required:
            raise ValueError("Missing required path argument")
        return default

    if not os.path.exists(path):
        if required:
            raise FileNotFoundError(f"JSON file not found: {path}")
        return default

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def as_float(value, default=None):
    if value is None:
        return default

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace(",", ".")
    if not text:
        return default

    try:
        return float(text)
    except ValueError:
        pass

    parts = text.split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        return default

    if len(parts) == 3:
        h, m, s = parts
        return h * 3600.0 + m * 60.0 + s

    if len(parts) == 2:
        m, s = parts
        return m * 60.0 + s

    return default


def as_int(value, default=None):
    try:
        if value is None:
            return default
        return int(round(float(value)))
    except Exception:
        return default


def roundf(value, digits=4, default=None):
    value = as_float(value, default)
    if value is None:
        return default
    return round(value, digits)


def clamp(value, min_value=0.0, max_value=1.0):
    return max(min_value, min(max_value, value))


def safe_mean(values, default=None):
    clean = [as_float(v, None) for v in values]
    clean = [v for v in clean if v is not None]
    if not clean:
        return default
    return mean(clean)


def seconds_to_frame(seconds, fps, default=None):
    seconds = as_float(seconds, None)
    fps = as_float(fps, None)
    if seconds is None or not fps:
        return default
    return int(round(seconds * fps))


def frame_to_seconds(frame, fps, default=None):
    frame = as_int(frame, None)
    fps = as_float(fps, None)
    if frame is None or not fps:
        return default
    return round(frame / fps, 4)


def compact_dict(d):
    if not isinstance(d, dict):
        return d
    return {k: v for k, v in d.items() if v is not None}


# -------------------------
# Source normalization
# -------------------------

def get_shots(shots_data):
    if isinstance(shots_data, list):
        return shots_data

    if isinstance(shots_data, dict):
        for key in ("shots", "cuts", "scenes"):
            if isinstance(shots_data.get(key), list):
                return shots_data[key]

    raise ValueError("Could not find shots list in proxy_shots JSON")


def detect_fps(transitions_data, beatmap_data, shots_data, motion_data):
    candidates = [
        transitions_data.get("fps") if isinstance(transitions_data, dict) else None,
        (motion_data.get("video_info", {}) or {}).get("fps") if isinstance(motion_data, dict) else None,
        motion_data.get("fps") if isinstance(motion_data, dict) else None,
        beatmap_data.get("fps") if isinstance(beatmap_data, dict) else None,
        shots_data.get("fps") if isinstance(shots_data, dict) else None,
    ]

    for candidate in candidates:
        fps = as_float(candidate, None)
        if fps and fps > 0:
            return fps

    return 24.0


def detect_frame_count(transitions_data, beatmap_data, shots_data, motion_data, duration, fps):
    candidates = [
        transitions_data.get("frame_count") if isinstance(transitions_data, dict) else None,
        (motion_data.get("video_info", {}) or {}).get("frame_count") if isinstance(motion_data, dict) else None,
        motion_data.get("frame_count") if isinstance(motion_data, dict) else None,
        shots_data.get("frame_count") if isinstance(shots_data, dict) else None,
    ]

    for candidate in candidates:
        frame_count = as_int(candidate, None)
        if frame_count and frame_count > 0:
            return frame_count

    if duration and fps:
        return seconds_to_frame(duration, fps, None)

    return None


def normalize_shot(shot, index, fps=24.0):
    shot_id = as_int(shot.get("shot_id", shot.get("scene_index", shot.get("index", index + 1))), index + 1)

    start = roundf(shot.get("start_seconds", shot.get("start_time", shot.get("start"))), 4, 0.0)
    end = roundf(shot.get("end_seconds", shot.get("end_time", shot.get("end"))), 4, start)
    duration = roundf(shot.get("duration_seconds", shot.get("duration")), 4, None)

    if duration is None:
        duration = roundf(end - start, 4, 0.0)

    start_frame = as_int(shot.get("start_frame"), None)
    end_frame = as_int(shot.get("end_frame"), None)

    if start_frame is None:
        start_frame = seconds_to_frame(start, fps, None)

    if end_frame is None:
        end_frame = seconds_to_frame(end, fps, None)

    duration_frames = None
    if start_frame is not None and end_frame is not None:
        duration_frames = max(1, end_frame - start_frame)
    elif duration is not None:
        duration_frames = max(1, seconds_to_frame(duration, fps, 1))

    return {
        "shot_id": shot_id,
        "index": index,
        "start_seconds": start,
        "end_seconds": end,
        "duration_seconds": duration,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "duration_frames": duration_frames,
    }


def derive_zoom_direction_from_motion(motion):
    if not isinstance(motion, dict):
        return None

    motion_type = str(motion.get("motion_type") or "").lower()
    motion_family = str(motion.get("motion_family") or "").lower()

    if motion_family == "push_in" or "push_in" in motion_type or "zoom_in" in motion_type:
        return "in"

    if motion_family == "pull_out" or "pull_out" in motion_type or "zoom_out" in motion_type:
        return "out"

    return None


def normalize_motion_segment(segment):
    if not isinstance(segment, dict):
        segment = {}

    normalized = {
        "shot_id": as_int(segment.get("shot_id"), None),
        "motion_type": segment.get("motion_type"),
        "motion_family": segment.get("motion_family"),
        "motion_intensity": segment.get("motion_intensity"),
        "confidence": segment.get("confidence"),
        "camera_motion": segment.get("camera_motion", {}),
        "speed_change": segment.get("speed_change"),
        "speed_change_confidence": segment.get("speed_change_confidence"),
        "speed_ramp_candidate": bool(segment.get("speed_ramp_candidate", False)),
        "speed_ramp_filter_reason": segment.get("speed_ramp_filter_reason"),
        "raw_metrics": segment.get("metrics") or segment.get("raw_metrics") or {},
    }

    normalized["zoom_direction"] = derive_zoom_direction_from_motion(normalized)
    normalized["zoom_candidate"] = normalized["zoom_direction"] in {"in", "out"}
    normalized["motion_based_zoom"] = {
        "candidate": normalized["zoom_candidate"],
        "direction": normalized["zoom_direction"],
        "confidence": normalized.get("confidence"),
        "motion_family": normalized.get("motion_family"),
        "motion_type": normalized.get("motion_type"),
        "motion_intensity": normalized.get("motion_intensity"),
    }

    return normalized


def transition_type_is_concrete(transition_type):
    text = str(transition_type or "").lower()
    if not text:
        return False

    bad_tokens = [
        "candidate",
        "unknown",
        "simple_cut",
        "hard_cut",
        "none",
        "no_transition",
    ]

    return not any(token in text for token in bad_tokens)


def default_transition_duration_frames(transition_type, confidence, strength, fps):
    transition_type_l = str(transition_type or "").lower()
    confidence_l = str(confidence or "").lower()
    strength_f = as_float(strength, 0.0) or 0.0

    if not transition_type_is_concrete(transition_type_l):
        return 0

    # Short-form reels usually use very short transitions.
    if "whip" in transition_type_l or "swipe" in transition_type_l:
        base = 6
    elif "glitch" in transition_type_l or "flash" in transition_type_l or "zoom" in transition_type_l:
        base = 5
    elif "dip" in transition_type_l or "black" in transition_type_l:
        base = 8
    elif "dissolve" in transition_type_l or "fade" in transition_type_l:
        base = 10
    else:
        base = 8

    if strength_f >= 0.65:
        base += 3
    elif strength_f <= 0.25:
        base -= 2

    if confidence_l == "medium":
        base = max(4, base - 2)

    # Keep transition short enough for short social clips.
    return int(clamp(base, 2, max(2, round((fps or 24.0) * 0.65))))


def normalize_transition(transition, fps=24.0):
    scores = transition.get("scores", {}) or {}
    strength = roundf(
        transition.get("transition_strength", scores.get("transition_strength")),
        4,
        None,
    )
    transition_type = transition.get("transition_type")
    confidence = transition.get("confidence")
    duration_frames = as_int(
        transition.get("duration_frames", transition.get("estimated_duration_frames")),
        None,
    )

    if duration_frames is None:
        duration_frames = default_transition_duration_frames(transition_type, confidence, strength, fps)

    outgoing_frames = int(duration_frames // 2)
    incoming_frames = int(duration_frames - outgoing_frames)

    cut_time = roundf(transition.get("cut_time"), 4, None)
    cut_frame = as_int(transition.get("cut_frame"), None)

    if cut_frame is None:
        cut_frame = seconds_to_frame(cut_time, fps, None)

    if cut_time is None:
        cut_time = frame_to_seconds(cut_frame, fps, None)

    concrete = transition_type_is_concrete(transition_type)
    high_confidence = str(confidence or "").lower() == "high"

    return {
        "from_shot": as_int(transition.get("from_shot"), None),
        "to_shot": as_int(transition.get("to_shot"), None),
        "cut_time": cut_time,
        "cut_frame": cut_frame,
        "transition_type": transition_type,
        "confidence": confidence,
        "transition_strength": strength,
        "duration_frames": duration_frames,
        "duration_seconds": roundf(duration_frames / fps, 4, 0.0) if fps else None,
        "side": "centered" if duration_frames else "none",
        "placement": "at_cut" if duration_frames else "none",
        "outgoing_frames": outgoing_frames,
        "incoming_frames": incoming_frames,
        "is_concrete": concrete,
        "is_high_confidence": high_confidence,
        "is_editor_candidate": bool(concrete and high_confidence and duration_frames > 0),
        "scores": scores,
        "reasons": transition.get("reasons", []),
        "raw": transition,
    }


def normalize_beat(beat, fps=24.0):
    t = roundf(beat.get("time"), 4, None)
    return {
        "index": as_int(beat.get("index"), None),
        "time": t,
        "frame": as_int(beat.get("frame"), seconds_to_frame(t, fps, None)),
        "source": beat.get("source"),
        "is_downbeat": bool(beat.get("is_downbeat", False)),
    }


def normalize_energy_peak(peak, fps=24.0):
    t = roundf(peak.get("time"), 4, None)
    return {
        "index": as_int(peak.get("index"), None),
        "time": t,
        "frame": as_int(peak.get("frame"), seconds_to_frame(t, fps, None)),
        "strength": roundf(peak.get("strength"), 4, None),
        "source": peak.get("source"),
    }


# -------------------------
# Transcript and caption style
# -------------------------

def normalize_transcript_word(word, segment_start=None, fps=24.0):
    if not isinstance(word, dict):
        return None

    start = as_float(word.get("start"), None)
    end = as_float(word.get("end"), None)

    if start is None and segment_start is not None:
        start = segment_start

    text = str(word.get("word", word.get("text", ""))).strip()
    if not text:
        return None

    return compact_dict({
        "word": text,
        "text": text,
        "start": roundf(start, 4, None),
        "end": roundf(end, 4, None),
        "start_frame": seconds_to_frame(start, fps, None),
        "end_frame": seconds_to_frame(end, fps, None),
        "probability": roundf(word.get("probability"), 4, None),
        "score": roundf(word.get("score"), 4, None),
    })


def normalize_transcript_segment(segment, index=0, fps=24.0):
    if not isinstance(segment, dict):
        return None

    start = as_float(segment.get("start", segment.get("start_seconds")), None)
    end = as_float(segment.get("end", segment.get("end_seconds")), None)
    text = str(segment.get("text", "")).strip()

    if start is None or end is None:
        return None

    words = []
    for w in segment.get("words", []) or []:
        normalized_word = normalize_transcript_word(w, start, fps)
        if normalized_word:
            words.append(normalized_word)

    return {
        "index": as_int(segment.get("id", segment.get("index")), index),
        "start": roundf(start, 4, None),
        "end": roundf(end, 4, None),
        "duration": roundf(end - start, 4, None),
        "start_frame": seconds_to_frame(start, fps, None),
        "end_frame": seconds_to_frame(end, fps, None),
        "text": text,
        "words": words,
        "words_count": len(words) if words else len(text.split()),
        "avg_logprob": roundf(segment.get("avg_logprob"), 4, None),
        "no_speech_prob": roundf(segment.get("no_speech_prob"), 4, None),
    }


def normalize_transcript(transcript_data, fps=24.0):
    """
    Accepts several common transcript shapes:
    - faster-whisper wrapper: {success, segments, text, language, duration}
    - raw: {segments, text}
    - list of segments
    """
    if transcript_data is None:
        return {
            "available": False,
            "text": "",
            "segments": [],
            "language": None,
            "language_probability": None,
            "duration": None,
            "words_count": 0,
        }

    if isinstance(transcript_data, list):
        raw_segments = transcript_data
        wrapper = {}
    elif isinstance(transcript_data, dict):
        raw_segments = transcript_data.get("segments", []) or []
        wrapper = transcript_data
    else:
        return {
            "available": False,
            "text": "",
            "segments": [],
            "language": None,
            "language_probability": None,
            "duration": None,
            "words_count": 0,
            "raw_type": type(transcript_data).__name__,
        }

    segments = []
    for i, seg in enumerate(raw_segments):
        normalized = normalize_transcript_segment(seg, i, fps)
        if normalized:
            segments.append(normalized)

    text = wrapper.get("text") if isinstance(wrapper, dict) else None
    if text is None:
        text = " ".join([str(s.get("text", "")).strip() for s in segments if isinstance(s, dict)]).strip()

    words_count = sum(as_int(s.get("words_count"), 0) for s in segments)

    return {
        "available": bool(wrapper.get("success", True)) and (bool(text) or bool(segments)),
        "success": wrapper.get("success", True) if isinstance(wrapper, dict) else True,
        "language": wrapper.get("language") if isinstance(wrapper, dict) else None,
        "language_probability": wrapper.get("language_probability") if isinstance(wrapper, dict) else None,
        "duration": wrapper.get("duration") if isinstance(wrapper, dict) else None,
        "model": wrapper.get("model") if isinstance(wrapper, dict) else None,
        "device": wrapper.get("device") if isinstance(wrapper, dict) else None,
        "compute_type": wrapper.get("compute_type") if isinstance(wrapper, dict) else None,
        "text": text or "",
        "segments": segments,
        "segments_count": len(segments),
        "words_count": words_count,
    }


def segment_overlap(a_start, a_end, b_start, b_end):
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    if end <= start:
        return None
    return start, end


def transcript_segments_in_range(transcript, start, end, fps=24.0):
    segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
    out = []

    for seg in segments:
        seg_start = as_float(seg.get("start"), None)
        seg_end = as_float(seg.get("end"), None)

        if seg_start is None or seg_end is None:
            continue

        overlap = segment_overlap(seg_start, seg_end, start, end)
        if not overlap:
            continue

        overlap_start, overlap_end = overlap

        clipped = dict(seg)
        clipped["overlap_start"] = roundf(overlap_start, 4, None)
        clipped["overlap_end"] = roundf(overlap_end, 4, None)
        clipped["relative_start"] = roundf(overlap_start - start, 4, None)
        clipped["relative_end"] = roundf(overlap_end - start, 4, None)
        clipped["relative_start_frame"] = seconds_to_frame(overlap_start - start, fps, None)
        clipped["relative_end_frame"] = seconds_to_frame(overlap_end - start, fps, None)

        out.append(clipped)

    return out


def build_subtitle_candidates_for_shot(transcript_in_shot, shot, fps):
    candidates = []

    for index, seg in enumerate(transcript_in_shot):
        text = str(seg.get("text", "")).strip()
        if not text:
            continue

        rel_start = as_float(seg.get("relative_start"), 0.0) or 0.0
        rel_end = as_float(seg.get("relative_end"), as_float(seg.get("duration"), rel_start + 1.0))
        if rel_end is None or rel_end <= rel_start:
            rel_end = rel_start + 1.0

        candidates.append({
            "subtitle_id": f"shot_{shot['shot_id']}_sub_{index + 1:02d}",
            "shot_id": shot["shot_id"],
            "text": text,
            "source_segment_index": seg.get("index"),
            "start_seconds": roundf(shot["start_seconds"] + rel_start, 4, None),
            "end_seconds": roundf(shot["start_seconds"] + rel_end, 4, None),
            "relative_start": roundf(rel_start, 4, None),
            "relative_end": roundf(rel_end, 4, None),
            "start_frame": seconds_to_frame(shot["start_seconds"] + rel_start, fps, None),
            "end_frame": seconds_to_frame(shot["start_seconds"] + rel_end, fps, None),
            "relative_start_frame": seconds_to_frame(rel_start, fps, None),
            "relative_end_frame": seconds_to_frame(rel_end, fps, None),
            "words_count": seg.get("words_count", len(text.split())),
            "source": "transcript_segment",
        })

    return candidates


def first_value(dct, keys, default=None):
    if not isinstance(dct, dict):
        return default

    for key in keys:
        if key in dct and dct[key] is not None:
            return dct[key]

    return default


def normalize_caption_style(caption_style_data):
    if not isinstance(caption_style_data, dict):
        return {
            "available": False,
            "raw": caption_style_data,
            "resolved": build_default_caption_style(False),
        }

    nested_caption_style = caption_style_data.get("caption_style") if isinstance(caption_style_data.get("caption_style"), dict) else {}

    summary = (
        caption_style_data.get("summary")
        or caption_style_data.get("subtitle_style_summary")
        or nested_caption_style.get("summary")
        or {}
    )

    groups = (
        caption_style_data.get("groups")
        or caption_style_data.get("subtitle_groups")
        or nested_caption_style.get("groups")
        or []
    )

    resolved = resolve_caption_style(summary, groups)

    return {
        "available": True,
        "summary": summary,
        "groups": groups,
        "resolved": resolved,
        "raw": caption_style_data,
    }


def build_default_caption_style(available):
    return {
        "available": bool(available),
        "style_source": "detected" if available else "default",
        "placement": "bottom_center",
        "safe_area": {
            "horizontal_margin_ratio": 0.08,
            "vertical_margin_ratio": 0.12,
        },
        "text": {
            "case": "preserve",
            "font_family": None,
            "font_size_px": None,
            "font_weight": None,
            "fill_color": None,
            "stroke_color": None,
            "stroke_width_px": None,
            "shadow": None,
        },
        "box": {
            "has_box": False,
            "box_color": None,
            "box_opacity": None,
            "corner_radius_px": None,
        },
        "animation": {
            "style": "none",
            "per_word_highlight": False,
        },
        "confidence": "low" if not available else "medium",
    }


def infer_caption_placement(summary, groups):
    text = json.dumps({"summary": summary, "groups": groups}, ensure_ascii=False).lower()

    if "top" in text:
        vertical = "top"
    elif "center" in text or "middle" in text:
        vertical = "center"
    else:
        vertical = "bottom"

    if "left" in text:
        horizontal = "left"
    elif "right" in text:
        horizontal = "right"
    else:
        horizontal = "center"

    if vertical == "center" and horizontal == "center":
        return "center"

    return f"{vertical}_{horizontal}"


def resolve_caption_style(summary, groups):
    resolved = build_default_caption_style(True)

    if not isinstance(summary, dict):
        summary = {}

    # Robust extraction: detector output is allowed to evolve without breaking merge.
    font_size = first_value(summary, [
        "font_size_px",
        "median_font_size_px",
        "estimated_font_size_px",
        "font_size",
        "text_height_px",
    ])

    stroke_width = first_value(summary, [
        "stroke_width_px",
        "outline_width_px",
        "border_width_px",
    ])

    fill_color = first_value(summary, [
        "fill_color",
        "text_color",
        "dominant_text_color",
        "font_color",
    ])

    stroke_color = first_value(summary, [
        "stroke_color",
        "outline_color",
        "border_color",
    ])

    resolved["placement"] = first_value(summary, ["placement", "position"], infer_caption_placement(summary, groups))
    resolved["text"]["font_family"] = first_value(summary, ["font_family", "font"], None)
    resolved["text"]["font_size_px"] = as_int(font_size, None)
    resolved["text"]["font_weight"] = first_value(summary, ["font_weight", "weight"], None)
    resolved["text"]["fill_color"] = fill_color
    resolved["text"]["stroke_color"] = stroke_color
    resolved["text"]["stroke_width_px"] = as_int(stroke_width, None)
    resolved["text"]["shadow"] = first_value(summary, ["shadow", "has_shadow"], None)

    resolved["box"]["has_box"] = bool(first_value(summary, ["has_box", "background_box", "box_detected"], False))
    resolved["box"]["box_color"] = first_value(summary, ["box_color", "background_color"], None)
    resolved["box"]["box_opacity"] = first_value(summary, ["box_opacity", "background_opacity"], None)
    resolved["box"]["corner_radius_px"] = as_int(first_value(summary, ["corner_radius_px", "box_radius"], None), None)

    resolved["animation"]["style"] = first_value(summary, ["animation_style", "caption_animation"], "none")
    resolved["animation"]["per_word_highlight"] = bool(first_value(summary, ["per_word_highlight", "word_highlight"], False))

    confidence = first_value(summary, ["confidence", "style_confidence"], None)
    resolved["confidence"] = confidence if confidence in {"low", "medium", "high"} else "medium"

    return resolved


def build_subtitle_generation_contract(transcript, caption_style):
    transcript_available = bool(transcript.get("available"))
    caption_style_available = bool(caption_style.get("available"))

    return {
        "available": transcript_available,
        "enabled_recommended": transcript_available,
        "source": "transcript.segments" if transcript_available else None,
        "segments_count": transcript.get("segments_count", 0),
        "words_count": transcript.get("words_count", 0),
        "caption_style_available": caption_style_available,
        "caption_style_source": "detected" if caption_style_available else "default",
        "default_grouping": {
            "max_chars_per_caption": 42,
            "max_words_per_caption": 8,
            "min_duration_seconds": 0.55,
            "max_duration_seconds": 2.4,
            "prefer_segment_boundaries": True,
        },
        "placement_default": (caption_style.get("resolved") or {}).get("placement", "bottom_center"),
        "degrade_gracefully": True,
    }


# -------------------------
# Caption occlusion / foreground mask contract
# -------------------------

def normalize_caption_occlusion_event(event, index=0, fps=24.0):
    if not isinstance(event, dict):
        return None

    start = as_float(event.get("start"), None)
    end = as_float(event.get("end"), None)
    mid = as_float(event.get("mid"), None)

    if start is None and mid is not None:
        start = mid
    if end is None and mid is not None:
        end = mid + as_float(event.get("duration"), 0.18)

    if start is None:
        return None

    if end is None or end <= start:
        end = start + max(0.001, as_float(event.get("duration"), 0.18) or 0.18)

    if mid is None:
        mid = start + ((end - start) / 2.0)

    occlusion = event.get("occlusion") if isinstance(event.get("occlusion"), dict) else {}
    layering = event.get("layering") if isinstance(event.get("layering"), dict) else {}
    foreground = event.get("foreground") if isinstance(event.get("foreground"), dict) else {}
    renderer_hints = event.get("renderer_hints") if isinstance(event.get("renderer_hints"), dict) else {}

    detected = bool(occlusion.get("detected", layering.get("occluded_by_foreground", False)))
    needs_foreground_mask = bool(
        occlusion.get(
            "needs_foreground_mask",
            layering.get("foreground_mask_required", detected),
        )
    )

    score = roundf(occlusion.get("score"), 4, 0.0)
    label = str(occlusion.get("label") or ("medium" if detected else "none"))

    sample_times = event.get("sample_times") if isinstance(event.get("sample_times"), list) else []
    samples = event.get("samples") if isinstance(event.get("samples"), list) else []
    debug_frames = event.get("debug_frames") if isinstance(event.get("debug_frames"), list) else []

    return compact_dict({
        "index": as_int(event.get("index"), index),
        "id": str(event.get("id") or f"caption_occlusion_{index + 1:04d}"),
        "source": event.get("source"),
        "caption_event_id": event.get("caption_event_id"),
        "cue_id": event.get("cue_id"),
        "text": str(event.get("text") or "").strip(),
        "observed_text": str(event.get("observed_text") or "").strip(),
        "start": roundf(start, 4, None),
        "end": roundf(end, 4, None),
        "mid": roundf(mid, 4, None),
        "duration": roundf(end - start, 4, None),
        "start_frame": seconds_to_frame(start, fps, None),
        "end_frame": seconds_to_frame(end, fps, None),
        "mid_frame": seconds_to_frame(mid, fps, None),
        "bbox": event.get("bbox"),
        "normalized_bbox": event.get("normalized_bbox"),
        "center": event.get("center"),
        "style_profile_id": event.get("style_profile_id"),
        "occlusion": compact_dict({
            "detected": detected,
            "needs_foreground_mask": needs_foreground_mask,
            "score": score,
            "label": label,
            "reason": occlusion.get("reason"),
            "max_score": roundf(occlusion.get("max_score"), 4, None),
            "median_score": roundf(occlusion.get("median_score"), 4, None),
            "max_foreground_overlap": roundf(occlusion.get("max_foreground_overlap"), 4, None),
            "median_foreground_overlap": roundf(occlusion.get("median_foreground_overlap"), 4, None),
            "median_text_visibility": roundf(occlusion.get("median_text_visibility"), 4, None),
            "likely_text_in_front": occlusion.get("likely_text_in_front"),
        }),
        "foreground": compact_dict({
            "backend_requested": foreground.get("backend_requested"),
            "backend_counts": foreground.get("backend_counts"),
        }),
        "layering": compact_dict({
            "occluded_by_foreground": bool(layering.get("occluded_by_foreground", detected)),
            "foreground_mask_required": bool(layering.get("foreground_mask_required", needs_foreground_mask)),
            "recommended_layers": layering.get("recommended_layers"),
            "mask_bbox": layering.get("mask_bbox"),
            "mask_time_range": layering.get("mask_time_range"),
        }),
        "renderer_hints": compact_dict({
            "preferred_layer_type": renderer_hints.get("preferred_layer_type"),
            "resolve_target": renderer_hints.get("resolve_target"),
            "fcpxml_target": renderer_hints.get("fcpxml_target"),
            "openreel_target": renderer_hints.get("openreel_target"),
        }),
        # Keep sample data compact. The full occlusion JSON remains the source of
        # truth for per-frame debug overlays and raw segmentation attempts.
        "sample_times": sample_times,
        "samples_count": len(samples),
        "debug_frames": debug_frames,
    })


def normalize_caption_occlusion(caption_occlusion_data, fps=24.0):
    if not isinstance(caption_occlusion_data, dict):
        return {
            "available": False,
            "success": False,
            "events": [],
            "events_count": 0,
            "needs_foreground_mask_count": 0,
            "summary": {},
            "raw": caption_occlusion_data,
        }

    raw_events = (
        caption_occlusion_data.get("occlusion_events")
        or caption_occlusion_data.get("caption_occlusion_events")
        or caption_occlusion_data.get("events")
        or []
    )

    events = []
    if isinstance(raw_events, list):
        for i, event in enumerate(raw_events):
            normalized = normalize_caption_occlusion_event(event, i, fps=fps)
            if normalized:
                events.append(normalized)

    events = sorted(events, key=lambda e: (as_float(e.get("start"), 0.0) or 0.0, as_float(e.get("end"), 0.0) or 0.0, str(e.get("id"))))

    mask_events = [
        e for e in events
        if bool((e.get("occlusion") or {}).get("needs_foreground_mask"))
    ]

    detected_events = [
        e for e in events
        if bool((e.get("occlusion") or {}).get("detected"))
    ]

    summary = caption_occlusion_data.get("summary") if isinstance(caption_occlusion_data.get("summary"), dict) else {}
    normalization = caption_occlusion_data.get("normalization") if isinstance(caption_occlusion_data.get("normalization"), dict) else {}

    backend_counts = summary.get("backend_sample_counts") or {}
    label_counts = summary.get("occlusion_label_counts") or {}

    return {
        "available": bool(caption_occlusion_data.get("success", caption_occlusion_data.get("ok", False))) and bool(events),
        "success": bool(caption_occlusion_data.get("success", caption_occlusion_data.get("ok", False))),
        "analysis_version": caption_occlusion_data.get("analysis_version"),
        "schema": caption_occlusion_data.get("schema"),
        "schema_version": caption_occlusion_data.get("schema_version"),
        "events": events,
        "events_count": len(events),
        "detected_count": len(detected_events),
        "needs_foreground_mask_count": len(mask_events),
        "inferred_transcript_event_count": summary.get("inferred_transcript_event_count", normalization.get("inferred_transcript_event_count")),
        "raw_style_event_count": summary.get("raw_style_event_count", normalization.get("raw_style_event_count")),
        "style_events_missing_bbox_count": normalization.get("style_events_missing_bbox_count"),
        "backend_sample_counts": backend_counts,
        "occlusion_label_counts": label_counts,
        "segmentation_runtime": caption_occlusion_data.get("segmentation_runtime"),
        "performance_plan": caption_occlusion_data.get("performance_plan"),
        "partial": caption_occlusion_data.get("partial"),
        "summary": summary,
        "warnings": caption_occlusion_data.get("warnings", []),
        "errors": caption_occlusion_data.get("errors", []),
    }


def caption_occlusion_events_in_range(events, start, end, fps=24.0):
    out = []

    for event in events or []:
        event_start = as_float(event.get("start"), None)
        event_end = as_float(event.get("end"), None)

        if event_start is None or event_end is None:
            continue

        overlap = segment_overlap(event_start, event_end, start, end)
        if not overlap:
            continue

        overlap_start, overlap_end = overlap
        clipped = dict(event)
        clipped["overlap_start"] = roundf(overlap_start, 4, None)
        clipped["overlap_end"] = roundf(overlap_end, 4, None)
        clipped["relative_start"] = roundf(overlap_start - start, 4, None)
        clipped["relative_end"] = roundf(overlap_end - start, 4, None)
        clipped["relative_start_frame"] = seconds_to_frame(overlap_start - start, fps, None)
        clipped["relative_end_frame"] = seconds_to_frame(overlap_end - start, fps, None)
        out.append(clipped)

    return out


def summarize_caption_occlusion_for_shot(events):
    if not events:
        return {
            "available": False,
            "events": [],
            "events_count": 0,
            "detected_count": 0,
            "needs_foreground_mask": False,
            "needs_foreground_mask_count": 0,
            "max_score": 0.0,
            "labels": {},
            "recommended_layers": None,
        }

    detected = [
        e for e in events
        if bool((e.get("occlusion") or {}).get("detected"))
    ]

    mask_needed = [
        e for e in events
        if bool((e.get("occlusion") or {}).get("needs_foreground_mask"))
    ]

    scores = [
        as_float((e.get("occlusion") or {}).get("score"), 0.0) or 0.0
        for e in events
    ]

    labels = {}
    for event in events:
        label = str((event.get("occlusion") or {}).get("label") or "unknown")
        labels[label] = labels.get(label, 0) + 1

    recommended_layers = None
    if mask_needed:
        recommended_layers = (
            (mask_needed[0].get("layering") or {}).get("recommended_layers")
            or {
                "V1": "base_video",
                "V2": "editable_caption_text",
                "V3": "foreground_subject_matte_above_caption",
            }
        )

    return {
        "available": True,
        "events": events,
        "events_count": len(events),
        "detected_count": len(detected),
        "needs_foreground_mask": bool(mask_needed),
        "needs_foreground_mask_count": len(mask_needed),
        "max_score": roundf(max(scores) if scores else 0.0, 4, 0.0),
        "labels": labels,
        "recommended_layers": recommended_layers,
    }


def build_caption_occlusion_contract(caption_occlusion):
    available = bool(caption_occlusion.get("available"))
    events_count = as_int(caption_occlusion.get("events_count"), 0) or 0
    mask_count = as_int(caption_occlusion.get("needs_foreground_mask_count"), 0) or 0

    return {
        "available": available,
        "enabled_recommended": available and mask_count > 0,
        "events_count": events_count,
        "detected_count": as_int(caption_occlusion.get("detected_count"), 0) or 0,
        "needs_foreground_mask_count": mask_count,
        "source": "caption_occlusion.occlusion_events" if available else None,
        "editor_layer_contract": {
            "V1": "base_video",
            "V2": "editable_caption_text",
            "V3": "foreground_subject_matte_above_caption",
        } if mask_count > 0 else None,
        "backend_sample_counts": caption_occlusion.get("backend_sample_counts") or {},
        "occlusion_label_counts": caption_occlusion.get("occlusion_label_counts") or {},
        "degrade_gracefully": True,
    }


# -------------------------
# Full-resolution caption foreground RGBA asset contract
# -------------------------

EXPECTED_FOREGROUND_ASSET_SCOPE = "local_foreground_patch_intersecting_caption_region"


def _path_status(path_value):
    path_text = str(path_value or "").strip()
    if not path_text:
        return {
            "path": None,
            "exists": False,
            "is_file": False,
            "is_dir": False,
        }

    path = Path(path_text)
    return {
        "path": path_text,
        "exists": path.exists(),
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
    }


def _format_frame_path(pattern, frame):
    pattern = str(pattern or "")
    if not pattern:
        return None

    try:
        return pattern % int(frame)
    except Exception:
        return None


def normalize_caption_foreground_asset_span(span, index=0):
    if not isinstance(span, dict):
        return None

    span_id = str(span.get("span_id") or f"matte_span_{index + 1:04d}")
    timeline_start = as_int(
        span.get("timeline_frame_start", span.get("source_frame_start")),
        None,
    )
    timeline_end = as_int(
        span.get("timeline_frame_end_exclusive", span.get("source_frame_end_exclusive")),
        None,
    )

    if timeline_start is None or timeline_end is None or timeline_end <= timeline_start:
        return {
            "span_id": span_id,
            "complete": False,
            "editor_ready": False,
            "errors": ["invalid_timeline_frame_range"],
            "raw": span,
        }

    duration_frames = timeline_end - timeline_start
    declared_duration = as_int(span.get("duration_frames"), duration_frames)
    asset = span.get("rgba_asset") if isinstance(span.get("rgba_asset"), dict) else {}
    scope = str(span.get("asset_scope") or "")
    cue_ids = [
        str(cue_id)
        for cue_id in (span.get("affected_cue_ids") or [])
        if str(cue_id).strip()
    ]

    frame_count_expected = as_int(asset.get("frame_count_expected"), duration_frames)
    frame_count_written = as_int(asset.get("frame_count_written"), 0)
    event_dir_status = _path_status(asset.get("event_dir"))
    manifest_status = _path_status(asset.get("manifest"))
    contact_sheet_status = _path_status(asset.get("contact_sheet"))
    rgba_pattern = str(asset.get("rgba_pattern") or "")
    alpha_pattern = str(asset.get("alpha_pattern") or "")

    file_checks = []
    missing_rgba_frames = []
    missing_alpha_frames = []

    for timeline_frame in range(timeline_start, timeline_end):
        rgba_path = _format_frame_path(rgba_pattern, timeline_frame)
        alpha_path = _format_frame_path(alpha_pattern, timeline_frame)

        rgba_exists = bool(rgba_path and Path(rgba_path).is_file())
        alpha_exists = bool(alpha_path and Path(alpha_path).is_file())

        file_checks.append({
            "timeline_frame": timeline_frame,
            "rgba_path": rgba_path,
            "rgba_exists": rgba_exists,
            "alpha_path": alpha_path,
            "alpha_exists": alpha_exists,
        })

        if not rgba_exists:
            missing_rgba_frames.append(timeline_frame)
        if not alpha_exists:
            missing_alpha_frames.append(timeline_frame)

    errors = []
    if scope != EXPECTED_FOREGROUND_ASSET_SCOPE:
        errors.append(f"invalid_asset_scope:{scope or 'missing'}")
    if declared_duration != duration_frames:
        errors.append(
            f"duration_mismatch:declared={declared_duration},actual={duration_frames}"
        )
    if frame_count_expected != duration_frames:
        errors.append(
            f"frame_count_expected_mismatch:{frame_count_expected}/{duration_frames}"
        )
    if frame_count_written != duration_frames:
        errors.append(
            f"frame_count_written_mismatch:{frame_count_written}/{duration_frames}"
        )
    if not bool(span.get("complete")):
        errors.append("span_not_complete")
    if not bool(asset.get("complete")):
        errors.append("rgba_asset_not_complete")
    if not cue_ids:
        errors.append("affected_cue_ids_empty")
    if not event_dir_status["is_dir"]:
        errors.append("event_dir_missing")
    if not manifest_status["is_file"]:
        errors.append("manifest_missing")
    if missing_rgba_frames:
        errors.append(f"missing_rgba_frames:{len(missing_rgba_frames)}")
    if missing_alpha_frames:
        errors.append(f"missing_alpha_frames:{len(missing_alpha_frames)}")
    if span.get("errors"):
        errors.append(f"source_span_errors:{len(span.get('errors') or [])}")

    editor_ready = not errors

    normalized = {
        "index": index,
        "span_id": span_id,
        "complete": bool(span.get("complete")),
        "editor_ready": editor_ready,
        "asset_scope": scope,
        "timeline_frame_start": timeline_start,
        "timeline_frame_end_exclusive": timeline_end,
        "duration_frames": duration_frames,
        "timeline_start_seconds": frame_to_seconds(
            timeline_start,
            span.get("contract_fps"),
            None,
        ),
        "timeline_end_seconds": frame_to_seconds(
            timeline_end,
            span.get("contract_fps"),
            None,
        ),
        "contract_fps": roundf(span.get("contract_fps"), 6, None),
        "source_video_fps": roundf(span.get("source_video_fps"), 6, None),
        "timebase_remap_applied": bool(span.get("timebase_remap_applied")),
        "source_video_frame_start": as_int(span.get("source_video_frame_start"), None),
        "source_video_frame_end_exclusive": as_int(
            span.get("source_video_frame_end_exclusive"),
            None,
        ),
        "affected_cue_ids": cue_ids,
        "affected_texts": [
            str(value)
            for value in (span.get("affected_texts") or [])
            if str(value).strip()
        ],
        "caption_region": span.get("caption_region"),
        "rgba_asset": {
            "asset_type": asset.get("asset_type"),
            "event_dir": event_dir_status,
            "rgba_pattern": rgba_pattern or None,
            "alpha_pattern": alpha_pattern or None,
            "manifest": manifest_status,
            "contact_sheet": contact_sheet_status,
            "frame_count_expected": frame_count_expected,
            "frame_count_written": frame_count_written,
            "width": as_int(asset.get("width"), None),
            "height": as_int(asset.get("height"), None),
            "complete": bool(asset.get("complete")),
        },
        "quality": span.get("quality") or {},
        "file_checks": file_checks,
        "missing_rgba_frames": missing_rgba_frames,
        "missing_alpha_frames": missing_alpha_frames,
        "errors": errors,
    }

    return normalized


def normalize_caption_foreground_assets(asset_data):
    if not isinstance(asset_data, dict):
        return {
            "available": False,
            "success": False,
            "builder_version": None,
            "asset_spans": [],
            "asset_span_count": 0,
            "editor_ready_spans": [],
            "editor_ready_span_count": 0,
            "rgba_frames_count": 0,
            "affected_cue_ids": [],
            "ready_for_v4_import": False,
            "errors": ["asset_contract_missing_or_invalid"],
            "raw": asset_data,
        }

    raw_spans = asset_data.get("asset_spans") or []
    spans = []
    for index, span in enumerate(raw_spans):
        normalized = normalize_caption_foreground_asset_span(span, index)
        if normalized:
            spans.append(normalized)

    ready_spans = [span for span in spans if span.get("editor_ready")]
    affected_cue_ids = sorted({
        cue_id
        for span in ready_spans
        for cue_id in (span.get("affected_cue_ids") or [])
    })
    rgba_frames_count = sum(
        as_int(span.get("duration_frames"), 0) or 0
        for span in ready_spans
    )

    source_summary = asset_data.get("summary") if isinstance(asset_data.get("summary"), dict) else {}
    source_ready = bool(
        source_summary.get("ready_for_merge_analysis")
        and source_summary.get("ready_for_editor_compilers")
        and source_summary.get("ready_for_v4_import")
    )
    success = bool(asset_data.get("success") and asset_data.get("ok"))
    available = success and bool(spans)
    ready_for_v4_import = bool(
        available
        and source_ready
        and len(ready_spans) == len(spans)
        and len(ready_spans) > 0
    )

    errors = []
    if not success:
        errors.append("asset_contract_not_successful")
    if not spans:
        errors.append("asset_spans_empty")
    if len(ready_spans) != len(spans):
        errors.append(
            f"non_ready_asset_spans:{len(spans) - len(ready_spans)}"
        )
    if available and not source_ready:
        errors.append("source_readiness_flags_false")

    return {
        "available": available,
        "success": success,
        "schema": asset_data.get("schema"),
        "schema_version": asset_data.get("schema_version"),
        "builder_version": asset_data.get("builder_version"),
        "asset_spans": spans,
        "asset_span_count": len(spans),
        "editor_ready_spans": ready_spans,
        "editor_ready_span_count": len(ready_spans),
        "rgba_frames_count": rgba_frames_count,
        "affected_cue_ids": affected_cue_ids,
        "affected_cue_count": len(affected_cue_ids),
        "ready_for_merge_analysis": bool(source_summary.get("ready_for_merge_analysis")),
        "ready_for_editor_compilers": bool(source_summary.get("ready_for_editor_compilers")),
        "ready_for_v4_import": ready_for_v4_import,
        "timebase": asset_data.get("timebase") or {},
        "source_video_info": asset_data.get("source_video_info") or {},
        "local_occlusion_patch_config": asset_data.get(
            "local_occlusion_patch_config"
        ) or {},
        "summary": source_summary,
        "failures": asset_data.get("failures") or [],
        "warnings": asset_data.get("warnings") or [],
        "errors": errors,
    }


def caption_foreground_asset_spans_in_frame_range(spans, start_frame, end_frame):
    out = []

    start_frame = as_int(start_frame, None)
    end_frame = as_int(end_frame, None)
    if start_frame is None or end_frame is None or end_frame <= start_frame:
        return out

    for span in spans or []:
        span_start = as_int(span.get("timeline_frame_start"), None)
        span_end = as_int(span.get("timeline_frame_end_exclusive"), None)
        if span_start is None or span_end is None:
            continue

        overlap_start = max(start_frame, span_start)
        overlap_end = min(end_frame, span_end)
        if overlap_end <= overlap_start:
            continue

        clipped = dict(span)
        clipped["overlap_timeline_frame_start"] = overlap_start
        clipped["overlap_timeline_frame_end_exclusive"] = overlap_end
        clipped["overlap_duration_frames"] = overlap_end - overlap_start
        clipped["relative_start_frame"] = overlap_start - start_frame
        clipped["relative_end_frame_exclusive"] = overlap_end - start_frame
        clipped["asset_sequence_start_offset_frames"] = overlap_start - span_start
        out.append(clipped)

    return out


def summarize_caption_foreground_assets_for_shot(spans):
    spans = list(spans or [])
    ready_spans = [span for span in spans if span.get("editor_ready")]
    cue_ids = sorted({
        cue_id
        for span in ready_spans
        for cue_id in (span.get("affected_cue_ids") or [])
    })

    return {
        "available": bool(spans),
        "spans": spans,
        "spans_count": len(spans),
        "editor_ready_spans_count": len(ready_spans),
        "rgba_frames_count": sum(
            as_int(span.get("overlap_duration_frames"), 0) or 0
            for span in ready_spans
        ),
        "affected_cue_ids": cue_ids,
        "ready_for_v4_import": bool(spans) and len(ready_spans) == len(spans),
    }


def build_caption_foreground_asset_contract(caption_foreground_assets):
    return {
        "available": bool(caption_foreground_assets.get("available")),
        "success": bool(caption_foreground_assets.get("success")),
        "builder_version": caption_foreground_assets.get("builder_version"),
        "asset_span_count": caption_foreground_assets.get("asset_span_count", 0),
        "editor_ready_span_count": caption_foreground_assets.get(
            "editor_ready_span_count",
            0,
        ),
        "rgba_frames_count": caption_foreground_assets.get("rgba_frames_count", 0),
        "affected_cue_ids": caption_foreground_assets.get("affected_cue_ids", []),
        "affected_cue_count": caption_foreground_assets.get(
            "affected_cue_count",
            0,
        ),
        "asset_scope_required": EXPECTED_FOREGROUND_ASSET_SCOPE,
        "ready_for_merge_analysis": bool(
            caption_foreground_assets.get("ready_for_merge_analysis")
        ),
        "ready_for_editor_compilers": bool(
            caption_foreground_assets.get("ready_for_editor_compilers")
        ),
        "ready_for_v4_import": bool(
            caption_foreground_assets.get("ready_for_v4_import")
        ),
        "editor_layer_contract": {
            "V1": "base_video",
            "V3": "editable_caption_textplus",
            "V4": "local_foreground_rgba_patch_above_caption",
        } if caption_foreground_assets.get("ready_for_v4_import") else None,
        "timebase": caption_foreground_assets.get("timebase") or {},
        "degrade_gracefully": False,
    }


def validate_caption_foreground_asset_linkage(
    caption_occlusion,
    caption_foreground_assets,
):
    approved_cues = {
        str(event.get("cue_id"))
        for event in (caption_occlusion.get("events") or [])
        if str(event.get("cue_id") or "").strip()
        and bool((event.get("occlusion") or {}).get("needs_foreground_mask"))
    }
    asset_cues = set(caption_foreground_assets.get("affected_cue_ids") or [])

    orphan_asset_cues = sorted(asset_cues - approved_cues)
    missing_asset_cues = sorted(approved_cues - asset_cues)

    ready = bool(
        caption_foreground_assets.get("ready_for_v4_import")
        and not orphan_asset_cues
        and not missing_asset_cues
    )

    return {
        "ready": ready,
        "approved_occlusion_cue_ids": sorted(approved_cues),
        "foreground_asset_cue_ids": sorted(asset_cues),
        "orphan_asset_cue_ids": orphan_asset_cues,
        "missing_asset_cue_ids": missing_asset_cues,
        "cue_linkage_complete": not orphan_asset_cues and not missing_asset_cues,
    }



# -------------------------
# Lookup helpers
# -------------------------

def build_by_shot_id(items):
    out = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        shot_id = item.get("shot_id")
        if shot_id is not None:
            out[int(shot_id)] = item

    return out


def build_transition_by_from_shot(transitions):
    out = {}

    for item in transitions:
        from_shot = item.get("from_shot")
        if from_shot is not None:
            out[int(from_shot)] = item

    return out


def items_in_range(items, start, end, time_key="time"):
    result = []

    for item in items:
        t = item.get(time_key)
        if t is None:
            continue

        if start <= float(t) < end:
            result.append(item)

    return result


def nearest_item(items, target, time_key="time"):
    if target is None or not items:
        return None

    best = None
    best_distance = None

    for item in items:
        t = item.get(time_key)
        if t is None:
            continue

        d = abs(float(t) - float(target))

        if best is None or d < best_distance:
            best = item
            best_distance = d

    if best is None:
        return None

    out = dict(best)
    out["distance"] = roundf(best_distance, 4, None)
    return out


def count_by_key(items, key):
    out = {}

    for item in items:
        value = item.get(key)
        if value is None:
            continue
        out[value] = out.get(value, 0) + 1

    return out


# -------------------------
# Edit signal layer
# -------------------------

def classify_duration(duration):
    if duration is None:
        return "unknown"

    if duration < 0.8:
        return "very_short"

    if duration < 1.5:
        return "short"

    if duration < 3.0:
        return "medium"

    return "long"


def compute_cut_rhythm_label(shot_duration, bpm):
    if not bpm or not shot_duration:
        return "unknown"

    beat_duration = 60.0 / float(bpm)
    beats_per_shot = shot_duration / beat_duration

    if beats_per_shot < 1.5:
        return "faster_than_2_beats"

    if beats_per_shot < 2.5:
        return "around_2_beats"

    if beats_per_shot < 4.5:
        return "around_4_beats"

    return "longer_than_4_beats"


def compute_speed_ramp_profile(shot, motion, bpm=None, fps=24.0):
    motion = motion or {}
    source_profile = motion.get("speed_ramp_profile") or {}
    candidate = bool(motion.get("speed_ramp_candidate", source_profile.get("candidate", False)))
    return {
        "candidate": candidate,
        "actionable": False,
        "authority": "motion_heuristic_only",
        "source": source_profile.get("source", "optical_flow_p75_motion_curve"),
        "speed_change": source_profile.get("speed_change", motion.get("speed_change")),
        "confidence": source_profile.get("confidence", motion.get("speed_change_confidence")),
        "score": source_profile.get("score", motion.get("speed_change_score", 0.0)),
        "filter_reason": source_profile.get("filter_reason", motion.get("speed_ramp_filter_reason")),
        "speed_curve": source_profile.get("speed_curve", []),
        "missing_authority": "source-backed time mapping or original pre-retime footage",
        "reason": (
            "optical-flow motion change is not a measured playback-speed change; "
            "source-backed time mapping or original pre-retime footage is missing"
        ),
    }


def compute_zoom_profile(shot, motion, fps=24.0):
    direction = derive_zoom_direction_from_motion(motion)
    duration_frames = max(1, as_int(shot.get("duration_frames"), seconds_to_frame(shot.get("duration_seconds"), fps, 1)))
    intensity = str((motion or {}).get("motion_intensity") or "").lower()

    if direction not in {"in", "out"}:
        return {
            "candidate": False,
            "direction": None,
            "reason": "motion is not push_in/pull_out",
        }

    if intensity in {"high", "very_high"}:
        scale = 1.12
        strength = "medium"
    elif intensity == "medium":
        scale = 1.10
        strength = "medium"
    else:
        scale = 1.06
        strength = "subtle"

    if direction == "in":
        start_scale, end_scale = 1.0, scale
    else:
        start_scale, end_scale = scale, 1.0

    return {
        "candidate": True,
        "direction": direction,
        "strength": strength,
        "start_scale": round(start_scale, 4),
        "end_scale": round(end_scale, 4),
        "duration_frames": duration_frames,
        "keyframes": [
            {
                "relative_frame": 0,
                "scale": round(start_scale, 4),
                "zoom": round(start_scale, 4),
            },
            {
                "relative_frame": max(0, duration_frames - 1),
                "scale": round(end_scale, 4),
                "zoom": round(end_scale, 4),
            },
        ],
        "easing": "ease_in_out",
        "confidence": (motion or {}).get("confidence"),
    }


def build_transition_handle_check(transition, shot, next_shot, frame_count=None):
    if not transition:
        return None

    duration_frames = as_int(transition.get("duration_frames"), 0) or 0
    outgoing_frames = as_int(transition.get("outgoing_frames"), duration_frames // 2) or 0
    incoming_frames = as_int(transition.get("incoming_frames"), duration_frames - outgoing_frames) or 0

    current_duration = as_int(shot.get("duration_frames"), 0) or 0
    next_duration = as_int(next_shot.get("duration_frames"), 0) if next_shot else 0

    source_end = as_int(shot.get("end_frame"), None)
    next_start = as_int(next_shot.get("start_frame"), None) if next_shot else None
    source_start = as_int(shot.get("start_frame"), None)

    source_media_outgoing_handle = None
    if source_end is not None and frame_count is not None:
        source_media_outgoing_handle = max(0, frame_count - source_end)

    source_media_incoming_handle = None
    if next_start is not None:
        source_media_incoming_handle = max(0, next_start)

    previous_media_handle = max(0, source_start or 0)

    can_fit_within_clip_durations = (
        current_duration >= max(1, outgoing_frames)
        and (not next_shot or next_duration >= max(1, incoming_frames))
    )

    return {
        "required_outgoing_frames": outgoing_frames,
        "required_incoming_frames": incoming_frames,
        "current_shot_duration_frames": current_duration,
        "next_shot_duration_frames": next_duration if next_shot else None,
        "can_fit_within_clip_durations": bool(can_fit_within_clip_durations),
        "source_media_outgoing_handle_frames": source_media_outgoing_handle,
        "source_media_incoming_handle_frames": source_media_incoming_handle,
        "previous_media_handle_frames": previous_media_handle,
        "safe_for_editor_attempt": bool(
            transition.get("is_editor_candidate")
            and can_fit_within_clip_durations
        ),
    }


def enrich_transition_for_shot(transition, shot, next_shot, fps, frame_count=None):
    if not transition:
        return None

    enriched = dict(transition)
    enriched["handle_check"] = build_transition_handle_check(enriched, shot, next_shot, frame_count)

    cut_frame = as_int(enriched.get("cut_frame"), None)
    if cut_frame is None:
        cut_frame = as_int(shot.get("end_frame"), None)

    enriched["timeline_cut_frame"] = as_int(shot.get("timeline_end_frame"), None)
    enriched["source_cut_frame"] = cut_frame
    enriched["editor_actionable"] = bool(
        enriched.get("is_editor_candidate")
        and (enriched.get("handle_check") or {}).get("safe_for_editor_attempt")
    )

    return enriched


def build_beat_timing(shot, beats, downbeats, strong_onsets, energy_peaks, bpm, fps):
    start = shot["start_seconds"]
    end = shot["end_seconds"]
    mid = start + (end - start) * 0.5

    beats_in_shot = items_in_range(beats, start, end)
    downbeats_in_shot = items_in_range(downbeats, start, end)
    strong_onsets_in_shot = items_in_range(strong_onsets, start, end)
    energy_peaks_in_shot = items_in_range(energy_peaks, start, end)

    nearest_to_start = nearest_item(beats, start)
    nearest_to_end = nearest_item(beats, end)
    nearest_to_mid = nearest_item(beats, mid)
    nearest_downbeat_to_start = nearest_item(downbeats, start)
    nearest_downbeat_to_end = nearest_item(downbeats, end)

    duration = max(0.001, as_float(shot.get("duration_seconds"), end - start) or 0.001)
    beat_density = round(len(beats_in_shot) / duration, 4)
    avg_energy = safe_mean([p.get("strength") for p in energy_peaks_in_shot], None)

    preferred_cut = nearest_to_end or nearest_to_start
    preferred_cut_time = preferred_cut.get("time") if preferred_cut else None

    return {
        "beats": beats_in_shot,
        "downbeats": downbeats_in_shot,
        "strong_onsets": strong_onsets_in_shot,
        "major_energy_peaks": energy_peaks_in_shot,
        "beats_count": len(beats_in_shot),
        "downbeats_count": len(downbeats_in_shot),
        "strong_onsets_count": len(strong_onsets_in_shot),
        "major_energy_peaks_count": len(energy_peaks_in_shot),
        "beat_density": beat_density,
        "average_energy_peak_strength": roundf(avg_energy, 4, None),
        "nearest_beat_to_start": nearest_to_start,
        "nearest_beat_to_mid": nearest_to_mid,
        "nearest_beat_to_end": nearest_to_end,
        "nearest_downbeat_to_start": nearest_downbeat_to_start,
        "nearest_downbeat_to_end": nearest_downbeat_to_end,
        "preferred_cut_time": roundf(preferred_cut_time, 4, None),
        "preferred_cut_frame": seconds_to_frame(preferred_cut_time, fps, None),
        "bpm": roundf(bpm, 3, None),
    }


def build_edit_signals(shot, motion, transition_to_next, beat_timing, bpm, fps):
    duration = shot.get("duration_seconds")

    speed_profile = compute_speed_ramp_profile(shot, motion, bpm=bpm, fps=fps)
    zoom_profile = compute_zoom_profile(shot, motion, fps=fps)

    transition_type = None
    transition_confidence = None
    transition_strength = None
    transition_duration_frames = None
    transition_actionable = False

    if transition_to_next:
        transition_type = transition_to_next.get("transition_type")
        transition_confidence = transition_to_next.get("confidence")
        transition_strength = transition_to_next.get("transition_strength")
        transition_duration_frames = transition_to_next.get("duration_frames")
        transition_actionable = bool(transition_to_next.get("editor_actionable"))

    has_stylized_transition_candidate = bool(
        transition_to_next
        and transition_to_next.get("is_editor_candidate")
    )

    cut_priority_score = 0.0

    if duration is not None:
        if duration < 1.0:
            cut_priority_score += 0.25
        elif duration < 1.8:
            cut_priority_score += 0.15

    if speed_profile.get("candidate"):
        cut_priority_score += 0.25

    if has_stylized_transition_candidate:
        cut_priority_score += 0.2

    avg_energy = as_float(beat_timing.get("average_energy_peak_strength"), None)
    if avg_energy is not None and avg_energy > 0.55:
        cut_priority_score += 0.15

    if beat_timing.get("downbeats_count", 0) > 0:
        cut_priority_score += 0.1

    if zoom_profile.get("candidate"):
        cut_priority_score += 0.05

    cut_priority_score = round(min(cut_priority_score, 1.0), 4)

    return {
        "duration_class": classify_duration(duration),
        "cut_rhythm_label": compute_cut_rhythm_label(duration, bpm),
        "beats_in_shot_count": beat_timing.get("beats_count", 0),
        "downbeats_in_shot_count": beat_timing.get("downbeats_count", 0),
        "energy_peaks_in_shot_count": beat_timing.get("major_energy_peaks_count", 0),
        "first_beat_time": (beat_timing.get("beats") or [{}])[0].get("time") if beat_timing.get("beats") else None,
        "first_downbeat_time": (beat_timing.get("downbeats") or [{}])[0].get("time") if beat_timing.get("downbeats") else None,
        "nearest_beat_to_start": beat_timing.get("nearest_beat_to_start"),
        "nearest_beat_to_mid": beat_timing.get("nearest_beat_to_mid"),
        "nearest_beat_to_end": beat_timing.get("nearest_beat_to_end"),
        "nearest_downbeat_to_start": beat_timing.get("nearest_downbeat_to_start"),
        "nearest_downbeat_to_end": beat_timing.get("nearest_downbeat_to_end"),
        "preferred_cut_time": beat_timing.get("preferred_cut_time"),
        "preferred_cut_frame": beat_timing.get("preferred_cut_frame"),
        "beat_density": beat_timing.get("beat_density"),
        "speed_ramp_candidate": bool(speed_profile.get("candidate")),
        "speed_ramp_profile": speed_profile,
        "transition_to_next_type": transition_type,
        "transition_to_next_confidence": transition_confidence,
        "transition_to_next_strength": transition_strength,
        "transition_to_next_duration_frames": transition_duration_frames,
        "transition_to_next_editor_actionable": transition_actionable,
        "has_stylized_transition_candidate": has_stylized_transition_candidate,
        "motion_zoom_direction": zoom_profile.get("direction"),
        "zoom_candidate": bool(zoom_profile.get("candidate")),
        "zoom_profile": zoom_profile,
        "cut_priority_score": cut_priority_score,
    }


# -------------------------
# Main merger
# -------------------------

def build_analysis(transitions_data, beatmap_data, shots_data, motion_data, transcript_data=None, caption_style_data=None, caption_occlusion_data=None, caption_foreground_assets_data=None, job_id=None):
    prelim_duration = (
        motion_data.get("video_info", {}).get("duration")
        or beatmap_data.get("duration")
    )
    fps = detect_fps(transitions_data, beatmap_data, shots_data, motion_data)

    shots = [normalize_shot(s, i, fps=fps) for i, s in enumerate(get_shots(shots_data))]

    if prelim_duration is None and shots:
        prelim_duration = shots[-1]["end_seconds"]

    duration = (
        motion_data.get("video_info", {}).get("duration")
        or beatmap_data.get("duration")
        or (shots[-1]["end_seconds"] if shots else None)
    )
    frame_count = detect_frame_count(transitions_data, beatmap_data, shots_data, motion_data, duration, fps)

    transitions = [
        normalize_transition(t, fps=fps)
        for t in transitions_data.get("transitions", [])
    ]

    motion_segments = [
        normalize_motion_segment(s)
        for s in motion_data.get("segments", [])
    ]

    beats = [
        normalize_beat(b, fps=fps)
        for b in beatmap_data.get("beats", [])
    ]

    downbeats = [
        normalize_beat(b, fps=fps)
        for b in beatmap_data.get("downbeats", [])
    ]

    bar_positions = [
        b
        for b in beatmap_data.get("bar_positions", [])
    ]

    strong_onsets = [
        normalize_energy_peak(p, fps=fps)
        for p in beatmap_data.get("strong_onsets", [])
    ]

    major_energy_peaks = [
        normalize_energy_peak(p, fps=fps)
        for p in beatmap_data.get("major_energy_peaks", [])
    ]

    motion_by_shot = build_by_shot_id(motion_segments)
    transition_by_from_shot = build_transition_by_from_shot(transitions)

    bpm = beatmap_data.get("bpm")

    transcript = normalize_transcript(transcript_data, fps=fps)
    caption_style = normalize_caption_style(caption_style_data)
    caption_style_resolved = caption_style.get("resolved") or build_default_caption_style(False)
    subtitle_generation = build_subtitle_generation_contract(transcript, caption_style)

    caption_occlusion = normalize_caption_occlusion(caption_occlusion_data, fps=fps)
    caption_occlusion_contract = build_caption_occlusion_contract(caption_occlusion)
    caption_occlusion_events = caption_occlusion.get("events", [])

    caption_foreground_assets = normalize_caption_foreground_assets(
        caption_foreground_assets_data
    )
    caption_foreground_asset_contract = build_caption_foreground_asset_contract(
        caption_foreground_assets
    )
    caption_foreground_asset_linkage = validate_caption_foreground_asset_linkage(
        caption_occlusion,
        caption_foreground_assets,
    )
    caption_foreground_asset_spans = caption_foreground_assets.get(
        "asset_spans",
        [],
    )

    timeline_shots = []
    subtitle_candidates = []
    timeline_cursor_seconds = 0.0
    timeline_cursor_frame = 0

    for i, shot in enumerate(shots):
        shot_id = shot["shot_id"]
        next_shot = shots[i + 1] if i + 1 < len(shots) else None

        motion = motion_by_shot.get(shot_id, {})
        transition_to_next_raw = transition_by_from_shot.get(shot_id)
        transition_to_next = enrich_transition_for_shot(
            transition=transition_to_next_raw,
            shot=shot,
            next_shot=next_shot,
            fps=fps,
            frame_count=frame_count,
        ) if transition_to_next_raw else None

        timeline_start_seconds = roundf(timeline_cursor_seconds, 4, 0.0)
        duration_seconds = as_float(shot.get("duration_seconds"), 0.0) or 0.0
        timeline_end_seconds = roundf(timeline_start_seconds + duration_seconds, 4, timeline_start_seconds)

        duration_frames = as_int(shot.get("duration_frames"), seconds_to_frame(duration_seconds, fps, 1)) or 1
        timeline_start_frame = timeline_cursor_frame
        timeline_end_frame = timeline_start_frame + duration_frames

        enriched_shot_base = {
            **shot,
            "timeline_start_seconds": timeline_start_seconds,
            "timeline_end_seconds": timeline_end_seconds,
            "timeline_duration_seconds": roundf(duration_seconds, 4, 0.0),
            "timeline_start_frame": timeline_start_frame,
            "timeline_end_frame": timeline_end_frame,
            "timeline_duration_frames": duration_frames,
        }

        transcript_in_shot = transcript_segments_in_range(
            transcript,
            shot["start_seconds"],
            shot["end_seconds"],
            fps=fps,
        )
        shot_subtitle_candidates = build_subtitle_candidates_for_shot(transcript_in_shot, enriched_shot_base, fps=fps)
        subtitle_candidates.extend(shot_subtitle_candidates)

        shot_caption_occlusion_events = caption_occlusion_events_in_range(
            caption_occlusion_events,
            shot["start_seconds"],
            shot["end_seconds"],
            fps=fps,
        )
        shot_caption_occlusion = summarize_caption_occlusion_for_shot(shot_caption_occlusion_events)

        shot_caption_foreground_asset_spans = caption_foreground_asset_spans_in_frame_range(
            caption_foreground_asset_spans,
            timeline_start_frame,
            timeline_end_frame,
        )
        shot_caption_foreground_assets = summarize_caption_foreground_assets_for_shot(
            shot_caption_foreground_asset_spans
        )

        beat_timing = build_beat_timing(
            shot=enriched_shot_base,
            beats=beats,
            downbeats=downbeats,
            strong_onsets=strong_onsets,
            energy_peaks=major_energy_peaks,
            bpm=bpm,
            fps=fps,
        )

        edit_signals = build_edit_signals(
            shot=enriched_shot_base,
            motion=motion,
            transition_to_next=transition_to_next,
            beat_timing=beat_timing,
            bpm=bpm,
            fps=fps,
        )

        edit_signals["caption_occlusion_score"] = shot_caption_occlusion.get("max_score")
        edit_signals["caption_occlusion_events_count"] = shot_caption_occlusion.get("events_count", 0)
        edit_signals["foreground_caption_occlusion_detected"] = bool(shot_caption_occlusion.get("detected_count", 0))
        edit_signals["foreground_mask_required"] = bool(shot_caption_occlusion.get("needs_foreground_mask"))
        edit_signals["foreground_rgba_asset_ready"] = bool(
            shot_caption_foreground_assets.get("ready_for_v4_import")
        )
        edit_signals["foreground_rgba_asset_spans_count"] = (
            shot_caption_foreground_assets.get("editor_ready_spans_count", 0)
        )

        timeline_shots.append({
            **enriched_shot_base,
            "motion": motion or None,
            "motion_based_zoom": edit_signals.get("zoom_profile"),
            "speed_ramp_profile": edit_signals.get("speed_ramp_profile"),
            "transition_to_next": transition_to_next,
            "beat_timing": beat_timing,
            "rhythm": {
                # Backward-compatible aliases.
                "beats": beat_timing.get("beats", []),
                "downbeats": beat_timing.get("downbeats", []),
                "strong_onsets": beat_timing.get("strong_onsets", []),
                "major_energy_peaks": beat_timing.get("major_energy_peaks", []),
                "nearest_beat_to_start": beat_timing.get("nearest_beat_to_start"),
                "nearest_beat_to_mid": beat_timing.get("nearest_beat_to_mid"),
                "nearest_beat_to_end": beat_timing.get("nearest_beat_to_end"),
                "preferred_cut_time": beat_timing.get("preferred_cut_time"),
                "preferred_cut_frame": beat_timing.get("preferred_cut_frame"),
            },
            "transcript": {
                "segments": transcript_in_shot,
                "text": " ".join([str(s.get("text", "")).strip() for s in transcript_in_shot]).strip(),
                "segments_count": len(transcript_in_shot),
                "subtitle_candidates": shot_subtitle_candidates,
                "subtitle_candidates_count": len(shot_subtitle_candidates),
            },
            "caption_occlusion": shot_caption_occlusion,
            "caption_foreground_assets": shot_caption_foreground_assets,
            "edit_signals": edit_signals,
            "editor_contract": {
                "source_start_frame": shot.get("start_frame"),
                "source_end_frame": shot.get("end_frame"),
                "source_duration_frames": shot.get("duration_frames"),
                "timeline_start_frame": timeline_start_frame,
                "timeline_end_frame": timeline_end_frame,
                "timeline_duration_frames": duration_frames,
                "zoom_ready": bool(edit_signals.get("zoom_candidate")),
                "speed_ramp_ready": bool(
                    (edit_signals.get("speed_ramp_profile") or {}).get("actionable")
                ),
                "transition_ready": bool(transition_to_next and transition_to_next.get("editor_actionable")),
                "subtitles_ready": bool(shot_subtitle_candidates),
                "foreground_mask_requested": bool(
                    shot_caption_occlusion.get("needs_foreground_mask")
                ),
                "foreground_mask_ready": bool(
                    shot_caption_foreground_assets.get("ready_for_v4_import")
                ),
                "foreground_rgba_asset_ready": bool(
                    shot_caption_foreground_assets.get("ready_for_v4_import")
                ),
                "foreground_rgba_asset_spans_count": (
                    shot_caption_foreground_assets.get(
                        "editor_ready_spans_count",
                        0,
                    )
                ),
                "caption_occlusion_ready": bool(shot_caption_occlusion.get("available")),
                "beat_timing_ready": bool(beat_timing.get("beats_count", 0) > 0),
            },
        })

        timeline_cursor_seconds = timeline_end_seconds
        timeline_cursor_frame = timeline_end_frame

    quality_flags = []

    if len(shots) != len(motion_segments):
        quality_flags.append({
            "type": "count_mismatch",
            "message": "shots count and motion segments count differ",
            "shots_count": len(shots),
            "motion_segments_count": len(motion_segments),
        })

    if transitions_data.get("shot_count") and int(transitions_data.get("shot_count")) != len(shots):
        quality_flags.append({
            "type": "count_mismatch",
            "message": "transition file shot_count differs from proxy shots count",
            "transition_shot_count": transitions_data.get("shot_count"),
            "shots_count": len(shots),
        })

    if motion_data.get("video_info", {}).get("duration") and beatmap_data.get("duration"):
        diff = abs(float(motion_data["video_info"]["duration"]) - float(beatmap_data["duration"]))
        if diff > 0.25:
            quality_flags.append({
                "type": "duration_mismatch",
                "message": "motion/video duration and audio beatmap duration differ",
                "motion_duration": motion_data["video_info"]["duration"],
                "beatmap_duration": beatmap_data["duration"],
                "difference_seconds": round(diff, 4),
            })

    if not transcript.get("available"):
        quality_flags.append({
            "type": "missing_optional_layer",
            "message": "transcript unavailable; subtitle generation will be disabled or empty",
            "layer": "transcript",
        })

    if not caption_style.get("available"):
        quality_flags.append({
            "type": "missing_optional_layer",
            "message": "caption style unavailable; subtitle styling will use defaults",
            "layer": "caption_style",
        })

    if caption_occlusion_data is not None and not caption_occlusion.get("available"):
        quality_flags.append({
            "type": "optional_layer_unavailable",
            "message": "caption occlusion was provided but unavailable or empty; foreground-mask planning will be disabled",
            "layer": "caption_occlusion",
            "errors": caption_occlusion.get("errors", []),
            "warnings": caption_occlusion.get("warnings", []),
        })

    if (
        caption_foreground_assets_data is not None
        and not caption_foreground_assets.get("ready_for_v4_import")
    ):
        quality_flags.append({
            "type": "required_layer_invalid",
            "message": "caption foreground assets were provided but are not editor-ready",
            "layer": "caption_foreground_assets",
            "errors": caption_foreground_assets.get("errors", []),
            "failures": caption_foreground_assets.get("failures", []),
        })

    if (
        caption_occlusion.get("needs_foreground_mask_count", 0) > 0
        and not caption_foreground_asset_linkage.get("ready")
    ):
        quality_flags.append({
            "type": "caption_foreground_asset_linkage_incomplete",
            "message": "approved caption-occlusion cues do not match editor-ready foreground assets",
            "layer": "caption_foreground_assets",
            "linkage": caption_foreground_asset_linkage,
        })

    speed_ramp_candidates = [
        s for s in timeline_shots
        if (s.get("edit_signals") or {}).get("speed_ramp_candidate")
    ]

    zoom_candidates = [
        s for s in timeline_shots
        if (s.get("edit_signals") or {}).get("zoom_candidate")
    ]

    stylized_transition_candidates = [
        t for t in transitions
        if t.get("is_editor_candidate")
    ]

    actionable_transitions = [
        (s.get("transition_to_next") or {})
        for s in timeline_shots
        if (s.get("transition_to_next") or {}).get("editor_actionable")
    ]

    beat_timing_ready_count = [
        s for s in timeline_shots
        if (s.get("editor_contract") or {}).get("beat_timing_ready")
    ]

    foreground_mask_shots = [
        s for s in timeline_shots
        if (s.get("caption_occlusion") or {}).get("needs_foreground_mask")
    ]

    caption_occlusion_ready_shots = [
        s for s in timeline_shots
        if (s.get("caption_occlusion") or {}).get("available")
    ]

    caption_foreground_asset_shots = [
        s for s in timeline_shots
        if (s.get("caption_foreground_assets") or {}).get(
            "ready_for_v4_import"
        )
    ]

    rich_contract = {
        "ready": True,
        "fps_available": bool(fps),
        "frame_count_available": frame_count is not None,
        "timeline_frames_available": all(s.get("timeline_start_frame") is not None and s.get("timeline_end_frame") is not None for s in timeline_shots),
        "source_frames_available": all(s.get("start_frame") is not None and s.get("end_frame") is not None for s in timeline_shots),
        "zoom_profiles_available": len(zoom_candidates),
        "speed_ramp_profiles_available": len(speed_ramp_candidates),
        "transition_profiles_available": len(stylized_transition_candidates),
        "actionable_transitions_count": len(actionable_transitions),
        "subtitle_candidates_count": len(subtitle_candidates),
        "caption_style_resolved": bool(caption_style_resolved),
        "caption_occlusion_available": bool(caption_occlusion.get("available")),
        "caption_occlusion_events_count": caption_occlusion.get("events_count", 0),
        "foreground_mask_events_available": caption_occlusion.get("needs_foreground_mask_count", 0),
        "foreground_mask_shots_count": len(foreground_mask_shots),
        "caption_foreground_assets_available": bool(
            caption_foreground_assets.get("available")
        ),
        "caption_foreground_asset_spans_count": (
            caption_foreground_assets.get("asset_span_count", 0)
        ),
        "caption_foreground_editor_ready_spans_count": (
            caption_foreground_assets.get("editor_ready_span_count", 0)
        ),
        "caption_foreground_rgba_frames_count": (
            caption_foreground_assets.get("rgba_frames_count", 0)
        ),
        "caption_foreground_asset_shots_count": len(
            caption_foreground_asset_shots
        ),
        "caption_foreground_asset_linkage_ready": bool(
            caption_foreground_asset_linkage.get("ready")
        ),
        "caption_foreground_v4_ready": bool(
            caption_foreground_assets.get("ready_for_v4_import")
            and caption_foreground_asset_linkage.get("ready")
        ),
        "beat_timing_ready_count": len(beat_timing_ready_count),
    }

    output = {
        "success": True,
        "analysis_version": VERSION,
        "schema_version": "2.1",
        "created_at_unix": round(time.time(), 3),
        "job": {
            "job_id": job_id,
            "source_video": transitions_data.get("source_video") or motion_data.get("video_path"),
            "source_audio": beatmap_data.get("audio_path"),
            "duration_seconds": roundf(duration, 4, None),
            "fps": fps,
            "frame_count": frame_count,
            "timeline_duration_seconds": roundf(timeline_cursor_seconds, 4, None),
            "timeline_duration_frames": timeline_cursor_frame,
        },
        "summary": {
            "shot_count": len(shots),
            "duration_seconds": roundf(duration, 4, None),
            "timeline_duration_seconds": roundf(timeline_cursor_seconds, 4, None),
            "timeline_duration_frames": timeline_cursor_frame,
            "bpm": roundf(bpm, 3, None),
            "rhythm_confidence": beatmap_data.get("rhythm_confidence"),
            "beats_count": len(beats),
            "downbeats_count": len(downbeats),
            "strong_onsets_count": len(strong_onsets),
            "major_energy_peaks_count": len(major_energy_peaks),
            "transition_count": len(transitions),
            "transition_type_counts": count_by_key(transitions, "transition_type"),
            "actionable_transitions_count": len(actionable_transitions),
            "motion_summary": motion_data.get("motion_summary", {}),
            "speed_ramp_candidates_count": len(speed_ramp_candidates),
            "zoom_candidates_count": len(zoom_candidates),
            "stylized_transition_candidates_count": len(stylized_transition_candidates),
            "quality_flags_count": len(quality_flags),
            "transcript_available": transcript.get("available", False),
            "transcript_segments_count": transcript.get("segments_count", 0),
            "transcript_words_count": transcript.get("words_count", 0),
            "subtitle_candidates_count": len(subtitle_candidates),
            "caption_style_available": caption_style.get("available", False),
            "caption_occlusion_available": caption_occlusion.get("available", False),
            "caption_occlusion_events_count": caption_occlusion.get("events_count", 0),
            "caption_occlusion_detected_count": caption_occlusion.get("detected_count", 0),
            "caption_occlusion_needs_foreground_mask_count": caption_occlusion.get("needs_foreground_mask_count", 0),
            "caption_occlusion_shots_affected_count": len(caption_occlusion_ready_shots),
            "foreground_mask_shots_count": len(foreground_mask_shots),
            "caption_foreground_assets_available": caption_foreground_assets.get(
                "available",
                False,
            ),
            "caption_foreground_asset_spans_count": caption_foreground_assets.get(
                "asset_span_count",
                0,
            ),
            "caption_foreground_editor_ready_spans_count": (
                caption_foreground_assets.get("editor_ready_span_count", 0)
            ),
            "caption_foreground_rgba_frames_count": caption_foreground_assets.get(
                "rgba_frames_count",
                0,
            ),
            "caption_foreground_affected_cue_count": caption_foreground_assets.get(
                "affected_cue_count",
                0,
            ),
            "caption_foreground_asset_shots_count": len(
                caption_foreground_asset_shots
            ),
            "caption_foreground_asset_linkage_ready": (
                caption_foreground_asset_linkage.get("ready", False)
            ),
            "caption_foreground_v4_ready": rich_contract.get(
                "caption_foreground_v4_ready",
                False,
            ),
            "beat_timing_ready_count": len(beat_timing_ready_count),
            "rich_contract_ready": rich_contract.get("ready"),
        },
        "sources": {
            "transitions": {
                "version": transitions_data.get("version"),
                "summary": transitions_data.get("summary", {}),
                "runtime_sec": transitions_data.get("runtime_sec"),
            },
            "beatmap": {
                "analysis_version": beatmap_data.get("analysis_version"),
                "summary": beatmap_data.get("summary", beatmap_data.get("rhythm_summary", {})),
            },
            "shots": {
                "count": len(shots),
            },
            "motion": {
                "analysis_version": motion_data.get("analysis_version"),
                "summary": motion_data.get("motion_summary", {}),
            },
            "transcript": {
                "available": transcript.get("available", False),
                "language": transcript.get("language"),
                "segments_count": transcript.get("segments_count", 0),
                "words_count": transcript.get("words_count", 0),
                "model": transcript.get("model"),
                "device": transcript.get("device"),
                "compute_type": transcript.get("compute_type"),
            },
            "caption_style": {
                "available": caption_style.get("available", False),
                "summary": caption_style.get("summary", {}),
                "resolved": caption_style_resolved,
            },
            "caption_occlusion": {
                "available": caption_occlusion.get("available", False),
                "success": caption_occlusion.get("success", False),
                "analysis_version": caption_occlusion.get("analysis_version"),
                "events_count": caption_occlusion.get("events_count", 0),
                "detected_count": caption_occlusion.get("detected_count", 0),
                "needs_foreground_mask_count": caption_occlusion.get("needs_foreground_mask_count", 0),
                "backend_sample_counts": caption_occlusion.get("backend_sample_counts", {}),
                "occlusion_label_counts": caption_occlusion.get("occlusion_label_counts", {}),
                "segmentation_runtime": caption_occlusion.get("segmentation_runtime"),
            },
            "caption_foreground_assets": {
                "available": caption_foreground_assets.get("available", False),
                "success": caption_foreground_assets.get("success", False),
                "builder_version": caption_foreground_assets.get("builder_version"),
                "asset_span_count": caption_foreground_assets.get(
                    "asset_span_count",
                    0,
                ),
                "editor_ready_span_count": caption_foreground_assets.get(
                    "editor_ready_span_count",
                    0,
                ),
                "rgba_frames_count": caption_foreground_assets.get(
                    "rgba_frames_count",
                    0,
                ),
                "affected_cue_ids": caption_foreground_assets.get(
                    "affected_cue_ids",
                    [],
                ),
                "ready_for_v4_import": caption_foreground_assets.get(
                    "ready_for_v4_import",
                    False,
                ),
                "linkage": caption_foreground_asset_linkage,
            },
        },
        "caption_style_resolved": caption_style_resolved,
        "subtitle_generation": subtitle_generation,
        "caption_occlusion_contract": caption_occlusion_contract,
        "caption_foreground_asset_contract": caption_foreground_asset_contract,
        "caption_foreground_asset_linkage": caption_foreground_asset_linkage,
        "timeline": {
            "shots": timeline_shots,
            "beats": beats,
            "downbeats": downbeats,
            "bar_positions": bar_positions,
            "strong_onsets": strong_onsets,
            "major_energy_peaks": major_energy_peaks,
            "transitions": transitions,
            "motion_segments": motion_segments,
            "speed_ramp_candidates": speed_ramp_candidates,
            "zoom_candidates": zoom_candidates,
            "subtitle_candidates": subtitle_candidates,
            "transcript": transcript,
            "caption_style": caption_style,
            "caption_style_resolved": caption_style_resolved,
            "caption_occlusion": caption_occlusion,
            "caption_occlusion_events": caption_occlusion_events,
            "caption_foreground_assets": caption_foreground_assets,
            "caption_foreground_asset_spans": caption_foreground_asset_spans,
        },
        "rich_generic_contract": rich_contract,
        "planner_ready": {
            "recommended_inputs": [
                "timeline.shots",
                "timeline.shots[].edit_signals",
                "timeline.shots[].beat_timing",
                "timeline.shots[].motion_based_zoom",
                "timeline.shots[].speed_ramp_profile",
                "timeline.shots[].transition_to_next",
                "timeline.subtitle_candidates",
                "timeline.caption_style_resolved",
                "timeline.caption_occlusion",
                "timeline.shots[].caption_occlusion",
                "timeline.caption_foreground_assets",
                "timeline.caption_foreground_asset_spans",
                "timeline.shots[].caption_foreground_assets",
                "caption_foreground_asset_contract",
                "caption_foreground_asset_linkage",
                "summary",
                "rich_generic_contract",
            ],
            "notes": [
                "Use transition_to_next only when is_editor_candidate/editor_actionable is true.",
                "Treat speed_ramp_profile as non-actionable motion evidence unless it has source-backed retime authority.",
                "Use motion_based_zoom.keyframes instead of inventing zoom timing.",
                "Use beat_timing.preferred_cut_time/frame for beat-aware cut decisions.",
                "Use subtitle_candidates and caption_style_resolved for subtitle generation.",
                "Use caption_occlusion.needs_foreground_mask only as a request signal; do not invent matte assets.",
                "Use caption_foreground_asset_contract and timeline.caption_foreground_asset_spans for exact V4 RGBA paths and timing.",
                "Place only editor_ready local foreground patches above V3 Text+ captions.",
            ],
        },
        "quality_flags": quality_flags,
        "errors": [],
    }

    return output


def main():
    parser = argparse.ArgumentParser(
        description="Merge stable analyzer JSON files into one rich normalized analysis.json"
    )

    parser.add_argument("--transitions", required=True, help="Path to transitions.json")
    parser.add_argument("--beatmap", required=True, help="Path to beatmap.json")
    parser.add_argument("--shots", required=True, help="Path to proxy_shots/shots.json")
    parser.add_argument("--motion", required=True, help="Path to motion.json")
    parser.add_argument("--transcript", required=False, default=None, help="Optional path to transcript.json")
    parser.add_argument("--caption-style", required=False, default=None, help="Optional path to caption_style.json")
    parser.add_argument("--caption-occlusion", required=False, default=None, help="Optional path to caption_occlusion.json")
    parser.add_argument("--caption-foreground-assets", required=False, default=None, help="Optional path to caption_foreground_assets.json")
    parser.add_argument("--output", required=True, help="Path to analysis.json")
    parser.add_argument("--job-id", default=None)

    args = parser.parse_args()

    started = time.monotonic()

    transitions_data = load_json(args.transitions)
    beatmap_data = load_json(args.beatmap)
    shots_data = load_json(args.shots)
    motion_data = load_json(args.motion)
    transcript_data = load_json(args.transcript, required=False, default=None)
    caption_style_data = load_json(args.caption_style, required=False, default=None)
    caption_occlusion_data = load_json(args.caption_occlusion, required=False, default=None)
    caption_foreground_assets_data = load_json(
        args.caption_foreground_assets,
        required=False,
        default=None,
    )

    analysis = build_analysis(
        transitions_data=transitions_data,
        beatmap_data=beatmap_data,
        shots_data=shots_data,
        motion_data=motion_data,
        transcript_data=transcript_data,
        caption_style_data=caption_style_data,
        caption_occlusion_data=caption_occlusion_data,
        caption_foreground_assets_data=caption_foreground_assets_data,
        job_id=args.job_id,
    )

    analysis["runtime_sec"] = round(time.monotonic() - started, 4)

    save_json(args.output, analysis)

    print(json.dumps({
        "ok": True,
        "version": VERSION,
        "schema_version": analysis.get("schema_version"),
        "output": os.path.abspath(args.output),
        "runtime_sec": analysis["runtime_sec"],
        "shot_count": analysis["summary"]["shot_count"],
        "beats_count": analysis["summary"]["beats_count"],
        "transition_count": analysis["summary"]["transition_count"],
        "actionable_transitions_count": analysis["summary"]["actionable_transitions_count"],
        "speed_ramp_candidates_count": analysis["summary"]["speed_ramp_candidates_count"],
        "zoom_candidates_count": analysis["summary"]["zoom_candidates_count"],
        "subtitle_candidates_count": analysis["summary"]["subtitle_candidates_count"],
        "quality_flags_count": analysis["summary"]["quality_flags_count"],
        "transcript_available": analysis["summary"]["transcript_available"],
        "transcript_segments_count": analysis["summary"]["transcript_segments_count"],
        "caption_style_available": analysis["summary"]["caption_style_available"],
        "caption_occlusion_available": analysis["summary"].get("caption_occlusion_available"),
        "caption_occlusion_events_count": analysis["summary"].get("caption_occlusion_events_count"),
        "caption_occlusion_needs_foreground_mask_count": analysis["summary"].get("caption_occlusion_needs_foreground_mask_count"),
        "foreground_mask_shots_count": analysis["summary"].get("foreground_mask_shots_count"),
        "caption_foreground_asset_spans_count": analysis["summary"].get("caption_foreground_asset_spans_count"),
        "caption_foreground_editor_ready_spans_count": analysis["summary"].get("caption_foreground_editor_ready_spans_count"),
        "caption_foreground_rgba_frames_count": analysis["summary"].get("caption_foreground_rgba_frames_count"),
        "caption_foreground_asset_linkage_ready": analysis["summary"].get("caption_foreground_asset_linkage_ready"),
        "caption_foreground_v4_ready": analysis["summary"].get("caption_foreground_v4_ready"),
        "rich_contract_ready": analysis["summary"]["rich_contract_ready"],
    }, indent=2), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "version": VERSION,
            "error": str(e),
        }), file=sys.stderr, flush=True)
        raise
