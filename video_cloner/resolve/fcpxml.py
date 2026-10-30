#!/usr/bin/env python3
"""
compile_davinci_textplus_fcpxml.py

Video Cloner - DaVinci Resolve styled caption/title compiler.

Purpose
-------
Generate an importable FCPXML timeline containing editable styled title clips from
Video Cloner subtitle timings + detected caption style.

v1.2 full_timeline mode
-----------------------
Adds a Resolve-friendly `--timeline-mode full_timeline` path:

  V1 = video clips from generic_edit_commands.json, or one continuous fallback clip
  A1 = optional audio WAV underneath
  V2 = editable Basic Title/Text clips generated from subtitle_clips

This avoids the tedious manual step of importing a separate caption-only timeline
and copy/pasting the title clips into the edited timeline. It also keeps the
caption-only mode for debugging.

v1.3 native transition hints
----------------------------
Adds best-effort FCPXML transition emission for high-confidence `transition_hint`
operations from generic_edit_commands.json. Transitions are written between V1
video clips in full_timeline mode, using conservative Final Cut transition effect
UIDs that Resolve can attempt to import. If Resolve ignores a specific transition
type, the report still records the exact transition intent for later fallback
translators.

v1.4 hybrid transition backend
------------------------------
Keeps simple transitions as native FCPXML transitions, but routes advanced viral
transitions (blur, zoom blur, lens blur, whip pan, flash, flare, shake) into
invisible editable VFX placeholder clips on an upper video lane. These placeholders
preserve timing + effect intent so a later Resolve-internal controller pass can
apply Fusion/OFX-style effects without confusing native transition imports.


v1.5 per-cue caption styles
---------------------------
Consumes `caption_style_events` / `style_events` emitted by detect_caption_style.py
v5.2+. Instead of applying one global caption style to every Text/Title clip,
the compiler now matches each subtitle cue to the nearest detected visual caption
event and writes a separate text-style definition per cue.

This enables mixed-style videos where different words/phrases use different
font sizes, fill colors, stroke colors, shadows, and hook/spoken caption roles.
If no event matches a cue, the compiler falls back to the primary/global style.

Important
---------
This is still an FCPXML compiler, not a Resolve scripting adapter. It does not
need Resolve Studio/external scripting. Resolve imports the file normally via:
File -> Import Timeline -> Import AAF, EDL, XML...
"""

from __future__ import annotations

import argparse
import difflib
import html
import hashlib
import heapq
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

VERSION = "davinci_textplus_fcpxml_compiler_v1_6_visual_lifecycle"
SCHEMA = "video_cloner_davinci_textplus_fcpxml"
SCHEMA_VERSION = "1.6"
LIFECYCLE_PLAN_SCHEMA = "video_cloner_caption_lifecycle_authority_plan"
LIFECYCLE_TIMING_AUTHORITIES = {"visual_primary", "visual_primary_redetected", "transcript_fallback"}

# Resolve accepts this conservative Basic Title template better than more exotic
# generators. It imports as editable Title - Text clips with inspector controls.
DEFAULT_BASIC_TITLE_UID = ".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti"

# Conservative FCPXML transition effect UIDs. Resolve's importer support can vary,
# so v1.3 maps many transition hints to a small set of common native transitions.
# If a mapped effect is ignored by Resolve, the JSON report still preserves the
# transition intent for a future fallback/compound-clip translator.
TRANSITION_EFFECTS = {
    "cross_dissolve": {
        "name": "Cross Dissolve",
        "uid": ".../Transitions.localized/Dissolves.localized/Cross Dissolve.localized/Cross Dissolve.motr",
    },
    "fade_to_color": {
        "name": "Fade To Color",
        "uid": ".../Transitions.localized/Dissolves.localized/Fade To Color.localized/Fade To Color.motr",
    },
    "slide": {
        "name": "Slide",
        "uid": ".../Transitions.localized/Movements.localized/Slide.localized/Slide.motr",
    },
    "wipe": {
        "name": "Wipe",
        "uid": ".../Transitions.localized/Wipes.localized/Wipe.localized/Wipe.motr",
    },
}

CONFIDENCE_RANK = {"none": 0, "very_low": 1, "low": 2, "medium": 3, "high": 4, "very_high": 5}

# Hybrid transition routing. Simple editorial transitions stay native. Viral/VFX
# transitions become placeholder clips for a later Resolve/Fusion applier.
NATIVE_TRANSITION_KEYWORDS = (
    "dissolve", "cross", "blend", "opacity", "fade", "wipe", "reveal", "slide", "push", "swipe"
)
VFX_TRANSITION_KEYWORDS = (
    "blur", "zoom", "lens", "flare", "glow", "flash", "whip", "shake", "warp", "spin",
    "motion", "speed", "impact", "light", "luma", "swoosh", "smear", "camera"
)
CUT_ONLY_TRANSITION_KEYWORDS = (
    "hard_cut", "jump_cut", "straight_cut", "cut_only", "match_cut"
)



# -----------------------------------------------------------------------------
# Generic helpers
# -----------------------------------------------------------------------------


def now_unix() -> float:
    return time.time()


def write_json(path: str, data: Dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        f.flush()


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)



def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def str2bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    s = str(value).strip().lower()
    if s in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Boolean expected, got: {value}")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(round(float(value)))
    except Exception:
        return default


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def norm_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def xml_escape(text: Any) -> str:
    return html.escape(norm_text(text), quote=True)


def hex_to_rgb01(hex_color: Any, default: Tuple[float, float, float] = (1.0, 1.0, 1.0)) -> Tuple[float, float, float]:
    if not isinstance(hex_color, str):
        return default
    value = hex_color.strip().lstrip("#")
    if len(value) != 6:
        return default
    try:
        return (
            round(int(value[0:2], 16) / 255.0, 6),
            round(int(value[2:4], 16) / 255.0, 6),
            round(int(value[4:6], 16) / 255.0, 6),
        )
    except Exception:
        return default


def rgb01_to_fcpxml(rgb: Tuple[float, float, float], alpha: float = 1.0) -> str:
    r, g, b = [clamp(float(x), 0.0, 1.0) for x in rgb]
    a = clamp(float(alpha), 0.0, 1.0)
    return f"{r:.6g} {g:.6g} {b:.6g} {a:.6g}"


def sec_to_frames(sec: float, fps: float) -> int:
    return int(round(max(0.0, sec) * fps))


def frames_to_fcpx_time(frames: int, fps: float) -> str:
    fps_round = round(fps)
    if abs(fps - fps_round) < 1e-6 and fps_round > 0:
        return f"{int(frames)}/{int(fps_round)}s"
    return f"{frames / fps:.6f}s"


def path_to_file_url(path: str) -> str:
    """Return a FCPXML-friendly file:// URL for Windows or POSIX paths."""
    if not path:
        return ""
    p = str(path).strip().strip('"')
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", p):
        return p
    # Windows drive path: C:\folder\file.mp4 -> file:///C:/folder/file.mp4
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", p)
    if m:
        drive = m.group(1).upper()
        rest = m.group(2).replace("\\", "/")
        return f"file:///{drive}:/{quote(rest)}"
    # Windows UNC path: \\server\share\file -> file://server/share/file
    if p.startswith("\\\\"):
        rest = p.lstrip("\\").replace("\\", "/")
        return "file://" + quote(rest)
    try:
        return Path(p).resolve().as_uri()
    except Exception:
        return "file://" + quote(p.replace("\\", "/"))


def read_nested(data: Dict[str, Any], paths: Iterable[Iterable[str]], default: Any = None) -> Any:
    for path in paths:
        cur: Any = data
        ok = True
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                ok = False
                break
        if ok and cur is not None:
            return cur
    return default




def first_present(item: Dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    """Return the first key present even when its value is 0/False."""
    if not isinstance(item, dict):
        return default
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return default

def find_first_scalar(data: Any, keys: Iterable[str]) -> Optional[Any]:
    """Recursive small helper for paths like source_video/source_audio."""
    if isinstance(data, dict):
        for key in keys:
            if key in data and data[key]:
                return data[key]
        for value in data.values():
            found = find_first_scalar(value, keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = find_first_scalar(value, keys)
            if found is not None:
                return found
    return None


# -----------------------------------------------------------------------------
# Style extraction
# -----------------------------------------------------------------------------


def choose_style_profile(style_data: Dict[str, Any], profile_id: str = "primary") -> Dict[str, Any]:
    if not isinstance(style_data, dict):
        return {}

    if profile_id and profile_id not in {"primary", "resolved", "auto"}:
        for key in ("caption_style_profiles", "style_profiles"):
            for profile in style_data.get(key, []) or []:
                if isinstance(profile, dict) and profile.get("style_id") == profile_id:
                    return profile

    resolved = style_data.get("caption_style_resolved") or style_data.get("resolved") or {}
    primary_id = resolved.get("primary_style_id") if isinstance(resolved, dict) else None
    if primary_id:
        for key in ("caption_style_profiles", "style_profiles"):
            for profile in style_data.get(key, []) or []:
                if isinstance(profile, dict) and profile.get("style_id") == primary_id:
                    return profile

    profiles: List[Dict[str, Any]] = []
    for key in ("caption_style_profiles", "style_profiles"):
        for p in style_data.get(key, []) or []:
            if isinstance(p, dict):
                profiles.append(p)
    if profiles:
        def score(p: Dict[str, Any]) -> Tuple[float, int]:
            conf = safe_float((p.get("confidence") or {}).get("score"), 0.0)
            count = safe_int(p.get("sample_count"), 0)
            role_bonus = 0.1 if p.get("role") == "spoken_caption" else 0.0
            return (conf + role_bonus, count)
        profiles.sort(key=score, reverse=True)
        return profiles[0]

    return resolved if isinstance(resolved, dict) else {}


def extract_style_contract(style_data: Dict[str, Any], profile_id: str = "primary", overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    overrides = overrides or {}
    profile = choose_style_profile(style_data, profile_id=profile_id)
    resolved = style_data.get("caption_style_resolved") or style_data.get("resolved") or {}

    colors = profile.get("colors") or resolved.get("colors") or {}
    stroke = profile.get("stroke") or resolved.get("stroke") or {}
    shadow = profile.get("shadow") or resolved.get("shadow") or {}
    placement = profile.get("placement") or resolved.get("placement") or {}
    typography = profile.get("typography") or resolved.get("typography") or {}

    fill = overrides.get("fill") or colors.get("fill") or colors.get("text") or resolved.get("resolved_fill_color") or "#ffffff"
    outline = overrides.get("outline") or colors.get("stroke") or stroke.get("color") or resolved.get("resolved_stroke_color") or "#000000"
    shadow_color = overrides.get("shadow") or colors.get("shadow") or shadow.get("color") or outline

    font_name = overrides.get("font_name") or typography.get("font_family") or typography.get("font_name") or "Arial"
    if not font_name or str(font_name).lower() in {"unknown", "normal_or_unknown", "unknown_or_static_from_sampling"}:
        font_name = "Arial"

    font_size = safe_int(overrides.get("font_size") or typography.get("font_height_px") or resolved.get("font_height_px"), 60)
    font_size = max(8, font_size)

    font_scale = safe_float(overrides.get("font_scale"), 1.0)
    outline_scale = safe_float(overrides.get("outline_scale"), 1.0)
    shadow_scale = safe_float(overrides.get("shadow_scale"), 1.0)

    outline_px = safe_float(overrides.get("outline_px") or stroke.get("width_px_estimate") or resolved.get("outline_px"), 3.0)
    shadow_px = safe_float(overrides.get("shadow_px") or shadow.get("blur_px_estimate") or resolved.get("shadow_px"), 2.0)
    shadow_opacity = clamp(safe_float(overrides.get("shadow_opacity", shadow.get("opacity_estimate")), 0.85), 0.0, 1.0)
    # An explicit negative detector observation must not become a default effect.
    stroke_enabled = overrides.get("stroke_enabled", stroke.get("enabled")) is not False
    shadow_enabled = overrides.get("shadow_enabled", shadow.get("enabled")) is not False
    if not shadow_enabled:
        shadow_opacity = 0.0

    anchor = placement.get("anchor") or resolved.get("anchor") or {}
    x = safe_float(anchor.get("x"), 0.5)
    y = safe_float(anchor.get("y"), 0.6875)

    font_weight = str(typography.get("font_weight") or "").lower()
    bold = bool(overrides.get("bold", profile.get("bold", resolved.get("bold", font_weight == "bold"))))
    font_style = str(typography.get("font_style") or "").strip().lower()
    italic = bool(overrides.get("italic", profile.get("italic", resolved.get("italic", font_style in {"italic", "oblique"}))))

    return {
        "profile_id": profile.get("style_id") or resolved.get("primary_style_id") or profile_id,
        "role": profile.get("role") or "spoken_caption",
        "font_name": str(font_name),
        "font_size_px": int(round(font_size * font_scale)),
        "bold": bool(bold),
        "italic": bool(italic),
        "fill": fill,
        "outline": outline,
        "shadow": shadow_color,
        "fill_fcpxml": rgb01_to_fcpxml(hex_to_rgb01(fill), 1.0),
        "outline_fcpxml": rgb01_to_fcpxml(hex_to_rgb01(outline, (0.0, 0.0, 0.0)), 1.0 if stroke_enabled else 0.0),
        "shadow_fcpxml": rgb01_to_fcpxml(hex_to_rgb01(shadow_color, (0.0, 0.0, 0.0)), shadow_opacity),
        "outline_px": round(max(0.0, outline_px * outline_scale), 3) if stroke_enabled else 0.0,
        "shadow_px": round(max(0.0, shadow_px * shadow_scale), 3) if shadow_enabled else 0.0,
        "shadow_opacity": round(shadow_opacity, 4),
        "anchor": {"x": round(clamp(x, 0.0, 1.0), 5), "y": round(clamp(y, 0.0, 1.0), 5)},
        "placement": placement,
        "typography": typography,
        "source_profile": profile,
    }




# -----------------------------------------------------------------------------
# Per-cue caption style event support
# -----------------------------------------------------------------------------


def normalize_style_match_text(value: Any) -> str:
    text = norm_text(value).lower()
    text = re.sub(r"[^a-z0-9а-яё'’]+", " ", text, flags=re.IGNORECASE)
    text = text.replace("’", "'")
    return re.sub(r"\s+", " ", text).strip()


def normalized_style_cue_id(value: Any) -> Optional[int]:
    """Normalize transcript IDs only; group/event IDs are not individual cue authority."""
    match = re.fullmatch(r"sub_0*(\d+)", str(value or "").strip(), re.IGNORECASE)
    if not match:
        return None
    number = int(match.group(1))
    return number if number > 0 else None


def token_set(value: Any) -> set:
    normalized = normalize_style_match_text(value)
    return {t for t in normalized.split() if t}


def text_similarity_for_style(a: Any, b: Any) -> float:
    a_norm = normalize_style_match_text(a)
    b_norm = normalize_style_match_text(b)
    if not a_norm or not b_norm:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a_norm, b_norm).ratio()
    a_tokens = token_set(a_norm)
    b_tokens = token_set(b_norm)
    if not a_tokens or not b_tokens:
        return round(float(clamp(ratio, 0.0, 1.0)), 4)
    overlap = len(a_tokens & b_tokens) / max(1, min(len(a_tokens), len(b_tokens)))
    jaccard = len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens))
    containment = 1.0 if (a_norm in b_norm or b_norm in a_norm) else 0.0
    score = (0.45 * ratio) + (0.30 * overlap) + (0.15 * jaccard) + (0.10 * containment)
    return round(float(clamp(score, 0.0, 1.0)), 4)


def iter_dict_lists(data: Any, keys: Iterable[str]) -> List[Dict[str, Any]]:
    """Find first-class event lists without assuming an exact schema path."""
    wanted = set(keys)
    found: List[Dict[str, Any]] = []
    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in wanted and isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            found.append(item)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)
    walk(data)
    return found


def normalize_style_event(raw: Dict[str, Any], index: int, fps: float) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None

    text = norm_text(
        raw.get("text")
        or raw.get("cue_text")
        or raw.get("matched_text")
        or raw.get("observed_text")
        or raw.get("caption_text")
        or raw.get("ocr_text")
        or raw.get("label")
    )

    observed_text = norm_text(raw.get("observed_text") or raw.get("ocr_text") or raw.get("detected_text") or text)

    start = first_present(raw, ["start", "timeline_start", "start_seconds", "time_start"])
    end = first_present(raw, ["end", "timeline_end", "end_seconds", "time_end"])
    mid = first_present(raw, ["mid", "timestamp", "time", "sample_time", "sample_timestamp"])

    start_frame = first_present(raw, ["start_frame", "timeline_start_frame"])
    end_frame = first_present(raw, ["end_frame", "timeline_end_frame"])
    mid_frame = first_present(raw, ["mid_frame", "frame", "frame_index"])

    if start is None and start_frame is not None:
        start = safe_float(start_frame, 0.0) / fps
    if end is None and end_frame is not None:
        end = safe_float(end_frame, 0.0) / fps
    if mid is None and mid_frame is not None and ("frame_index" not in raw or "timestamp" not in raw):
        # Some detector outputs use frame_index as ordinal, not absolute video frame.
        # Only use it as time if it is explicitly a time-like frame key.
        key_names = set(raw.keys())
        if "mid_frame" in key_names or "frame" in key_names:
            mid = safe_float(mid_frame, 0.0) / fps

    if mid is None and start is not None and end is not None:
        mid = (safe_float(start, 0.0) + safe_float(end, 0.0)) / 2.0
    if start is None and mid is not None:
        half = max(0.05, safe_float(raw.get("duration") or raw.get("duration_seconds"), 0.35) / 2.0)
        start = max(0.0, safe_float(mid, 0.0) - half)
    if end is None and mid is not None:
        half = max(0.05, safe_float(raw.get("duration") or raw.get("duration_seconds"), 0.35) / 2.0)
        end = safe_float(mid, 0.0) + half

    if start is None or end is None:
        return None

    start_f = safe_float(start, 0.0)
    end_f = safe_float(end, start_f + 0.25)
    if end_f <= start_f:
        end_f = start_f + max(1.0 / fps, safe_float(raw.get("duration") or raw.get("duration_seconds"), 0.25))
    mid_f = safe_float(mid, (start_f + end_f) / 2.0)

    profile_id = (
        raw.get("style_profile_id")
        or raw.get("profile_id")
        or raw.get("style_id")
        or raw.get("caption_style_profile_id")
    )

    return {
        "index": index,
        "id": raw.get("id") or raw.get("event_id") or raw.get("cue_id") or raw.get("caption_id") or f"style_event_{index:04d}",
        "cue_id": raw.get("cue_id") or raw.get("subtitle_id") or raw.get("matched_cue_id"),
        "style_profile_id": profile_id,
        "text": text,
        "observed_text": observed_text,
        "start": round(start_f, 6),
        "end": round(end_f, 6),
        "mid": round(mid_f, 6),
        "duration": round(end_f - start_f, 6),
        "raw": raw,
    }


def extract_caption_style_events(style_data: Dict[str, Any], fps: float) -> List[Dict[str, Any]]:
    raw_events = []
    for key in ("caption_style_events", "style_events", "per_cue_style_events", "caption_events"):
        value = style_data.get(key) if isinstance(style_data, dict) else None
        if isinstance(value, list):
            raw_events.extend([x for x in value if isinstance(x, dict)])
    # Fallback: recursively find named event lists if top-level is not used.
    if not raw_events:
        raw_events = iter_dict_lists(style_data, ["caption_style_events", "style_events", "per_cue_style_events", "caption_events"])

    events: List[Dict[str, Any]] = []
    seen = set()
    for i, raw in enumerate(raw_events, start=1):
        event = normalize_style_event(raw, i, fps)
        if not event:
            continue
        visual_identity = raw.get("visual_event_identity")
        key = (
            ("visual_event_identity", visual_identity.strip())
            if isinstance(visual_identity, str) and visual_identity.strip()
            else (round(event["start"], 2), round(event["end"], 2), normalize_style_match_text(event.get("text") or event.get("observed_text")))
        )
        if key in seen:
            continue
        seen.add(key)
        events.append(event)
    return sorted(events, key=lambda e: (safe_float(e.get("start"), 0.0), safe_float(e.get("end"), 0.0), safe_int(e.get("index"), 0)))


def style_profile_lookup(style_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    if not isinstance(style_data, dict):
        return lookup
    for key in ("caption_style_profiles", "style_profiles"):
        for profile in style_data.get(key, []) or []:
            if isinstance(profile, dict) and profile.get("style_id"):
                lookup[str(profile.get("style_id"))] = profile
    return lookup


def deep_merge_dict(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    out = json.loads(json.dumps(base or {}, ensure_ascii=False, default=str))
    for key, value in (overlay or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge_dict(out[key], value)
        elif value is not None:
            out[key] = value
    return out


def event_to_synthetic_profile(event: Dict[str, Any], style_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert one detector event into a profile-like object consumed by extract_style_contract."""
    raw = event.get("raw") if isinstance(event.get("raw"), dict) else {}
    profile_id = event.get("style_profile_id") or raw.get("style_profile_id") or raw.get("profile_id") or raw.get("style_id")
    profiles = style_profile_lookup(style_data)
    base = profiles.get(str(profile_id), {}) if profile_id else {}

    # Gather direct event-level fields. v5.2 detector emits profile-like fields,
    # but older debug builds may emit estimated_* names only.
    colors = {}
    colors.update(raw.get("colors") if isinstance(raw.get("colors"), dict) else {})
    if raw.get("fill") or raw.get("fill_color") or raw.get("estimated_text_color"):
        colors["fill"] = raw.get("fill") or raw.get("fill_color") or raw.get("estimated_text_color")
    if raw.get("stroke") and isinstance(raw.get("stroke"), str):
        colors["stroke"] = raw.get("stroke")
    if raw.get("stroke_color") or raw.get("outline") or raw.get("estimated_stroke_color"):
        colors["stroke"] = raw.get("stroke_color") or raw.get("outline") or raw.get("estimated_stroke_color")
    if raw.get("shadow") and isinstance(raw.get("shadow"), str):
        colors["shadow"] = raw.get("shadow")
    if raw.get("shadow_color") or raw.get("estimated_shadow_color"):
        colors["shadow"] = raw.get("shadow_color") or raw.get("estimated_shadow_color")

    typography = {}
    typography.update(raw.get("typography") if isinstance(raw.get("typography"), dict) else {})
    if raw.get("font_height_px") or raw.get("font_size_px") or raw.get("estimated_font_height_px"):
        typography["font_height_px"] = raw.get("font_height_px") or raw.get("font_size_px") or raw.get("estimated_font_height_px")
    if raw.get("font_family") or raw.get("font_name"):
        typography["font_family"] = raw.get("font_family") or raw.get("font_name")
    if raw.get("font_weight"):
        typography["font_weight"] = raw.get("font_weight")
    if raw.get("case_style"):
        typography["case_style"] = raw.get("case_style")

    placement = {}
    placement.update(raw.get("placement") if isinstance(raw.get("placement"), dict) else {})
    anchor = raw.get("anchor") or raw.get("center")
    if isinstance(anchor, dict):
        placement["anchor"] = {
            "x": safe_float(anchor.get("x"), 0.5),
            "y": safe_float(anchor.get("y"), 0.6875),
            "coordinate_space": anchor.get("coordinate_space") or "normalized_frame",
        }
    elif isinstance(raw.get("bbox"), (list, tuple)) and len(raw.get("bbox")) >= 4:
        # If only normalized bbox exists, infer anchor. Raw bbox may be px or normalized.
        bbox = raw.get("normalized_bbox") if isinstance(raw.get("normalized_bbox"), (list, tuple)) else raw.get("bbox")
        if len(bbox) >= 4 and max([safe_float(x, 0.0) for x in bbox[:4]]) <= 1.5:
            placement["anchor"] = {
                "x": round((safe_float(bbox[0]) + safe_float(bbox[2])) / 2.0, 5),
                "y": round((safe_float(bbox[1]) + safe_float(bbox[3])) / 2.0, 5),
                "coordinate_space": "normalized_frame",
            }

    stroke = {}
    stroke.update(raw.get("stroke") if isinstance(raw.get("stroke"), dict) else {})
    if colors.get("stroke"):
        stroke["color"] = colors.get("stroke")
    if raw.get("stroke_width") or raw.get("outline_px") or raw.get("outline_width_px") or raw.get("stroke_width_px"):
        stroke["width_px_estimate"] = raw.get("stroke_width") or raw.get("outline_px") or raw.get("outline_width_px") or raw.get("stroke_width_px")
    if raw.get("has_dark_stroke") is not None and "enabled" not in stroke:
        stroke["enabled"] = bool(raw.get("has_dark_stroke"))

    shadow = {}
    shadow.update(raw.get("shadow") if isinstance(raw.get("shadow"), dict) else {})
    if colors.get("shadow"):
        shadow["color"] = colors.get("shadow")
    if raw.get("shadow_px") or raw.get("shadow_blur_px") or raw.get("shadow_blur_radius"):
        shadow["blur_px_estimate"] = raw.get("shadow_px") or raw.get("shadow_blur_px") or raw.get("shadow_blur_radius")
    if raw.get("has_shadow") is not None and "enabled" not in shadow:
        shadow["enabled"] = bool(raw.get("has_shadow"))

    overlay: Dict[str, Any] = {
        "style_id": f"event_style_{safe_int(event.get('index'), 0):04d}",
        "role": raw.get("role") or base.get("role") or "spoken_caption",
        "colors": colors,
        "typography": typography,
        "placement": placement,
        "stroke": stroke,
        "shadow": shadow,
        "animation": raw.get("animation") if isinstance(raw.get("animation"), dict) else {},
        "diagnostics": {
            "source_event_id": event.get("id"),
            "source_event_text": event.get("text"),
            "source_event_observed_text": event.get("observed_text"),
            "source_profile_id": profile_id,
        },
    }
    merged = deep_merge_dict(base, overlay)
    if not merged.get("style_id"):
        merged["style_id"] = overlay["style_id"]
    return merged


def build_event_style_contract(style_data: Dict[str, Any], event: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    profile = event_to_synthetic_profile(event, style_data)
    synthetic = {
        "caption_style_profiles": [profile],
        "caption_style_resolved": {},
    }
    contract = extract_style_contract(synthetic, profile_id=profile.get("style_id") or "event_style", overrides=overrides)
    contract["matched_style_event_id"] = event.get("id")
    contract["matched_style_event_index"] = event.get("index")
    contract["matched_style_event_text"] = event.get("text")
    contract["matched_style_event_observed_text"] = event.get("observed_text")
    contract["matched_style_profile_id"] = event.get("style_profile_id")
    return contract


def score_style_event_for_cue(cue: Dict[str, Any], event: Dict[str, Any], window_sec: float) -> Dict[str, Any]:
    cue_start = safe_float(cue.get("start"), 0.0)
    cue_end = safe_float(cue.get("end"), cue_start)
    cue_mid = (cue_start + cue_end) / 2.0
    ev_start = safe_float(event.get("start"), 0.0)
    ev_end = safe_float(event.get("end"), ev_start)
    ev_mid = safe_float(event.get("mid"), (ev_start + ev_end) / 2.0)

    overlap = max(0.0, min(cue_end, ev_end) - max(cue_start, ev_start))
    cue_dur = max(1e-6, cue_end - cue_start)
    ev_dur = max(1e-6, ev_end - ev_start)
    overlap_score = overlap / max(1e-6, min(cue_dur, ev_dur))

    distance = abs(cue_mid - ev_mid)
    proximity_score = clamp(1.0 - (distance / max(0.001, window_sec)), 0.0, 1.0)

    cue_text = cue.get("text") or ""
    event_text = event.get("text") or event.get("observed_text") or ""
    observed = event.get("observed_text") or event_text
    text_score = max(text_similarity_for_style(cue_text, event_text), text_similarity_for_style(cue_text, observed))

    cue_id = normalized_style_cue_id(cue.get("id") or cue.get("subtitle_id"))
    event_cue_id = normalized_style_cue_id(event.get("cue_id"))
    cue_id_score = 1.0 if cue_id is not None and cue_id == event_cue_id else 0.0

    # Timing is strongest because style events are generated from sampled frames.
    score = (0.42 * overlap_score) + (0.28 * proximity_score) + (0.22 * text_score) + (0.08 * cue_id_score)
    # Exact overlap is a very strong signal even when OCR text is partial.
    if overlap_score > 0.0:
        score += 0.08
    return {
        "score": round(float(clamp(score, 0.0, 1.0)), 4),
        "overlap_score": round(float(clamp(overlap_score, 0.0, 1.0)), 4),
        "proximity_score": round(float(clamp(proximity_score, 0.0, 1.0)), 4),
        "text_score": round(float(clamp(text_score, 0.0, 1.0)), 4),
        "cue_id_score": cue_id_score,
        "distance_sec": round(float(distance), 4),
    }


def assign_style_events_to_cues(
    cues: List[Dict[str, Any]],
    style_data: Dict[str, Any],
    base_style: Dict[str, Any],
    overrides: Dict[str, Any],
    fps: float,
    enabled: bool = True,
    match_window_sec: float = 1.25,
    min_match_score: float = 0.12,
) -> Tuple[Dict[int, Dict[str, Any]], Dict[str, Any]]:
    events = extract_caption_style_events(style_data, fps=fps)
    info: Dict[str, Any] = {
        "enabled": bool(enabled),
        "raw_event_count": len(events),
        "matched_cue_count": 0,
        "fallback_cue_count": len(cues),
        "match_window_sec": match_window_sec,
        "min_match_score": min_match_score,
        "style_profile_usage": {},
        "first_matches": [],
        "note": "Each cue is matched to the nearest caption_style_event by timing + text. Unmatched cues use the primary/global style.",
    }
    if not enabled or not events or not cues:
        if not events:
            info["disabled_reason"] = "no_caption_style_events_found"
        elif not enabled:
            info["disabled_reason"] = "disabled_by_cli"
        return {}, info

    cue_styles: Dict[int, Dict[str, Any]] = {}
    usage: Dict[str, int] = {}
    matches: List[Dict[str, Any]] = []

    for cue in cues:
        cue_mid = (safe_float(cue.get("start"), 0.0) + safe_float(cue.get("end"), 0.0)) / 2.0
        source_cue_id = normalized_style_cue_id(cue.get("id") or cue.get("subtitle_id"))
        nearby = [
            ev for ev in events
            # A visual event explicitly linked to another cue cannot authorize
            # this cue's font or coordinates merely because their times overlap.
            if (not ev.get("cue_id") or (
                source_cue_id is not None
                and normalized_style_cue_id(ev.get("cue_id")) == source_cue_id
            ))
            and (
                abs(safe_float(ev.get("mid"), cue_mid) - cue_mid) <= max(0.001, match_window_sec)
                or (safe_float(ev.get("start"), 0.0) <= safe_float(cue.get("end"), 0.0) and safe_float(ev.get("end"), 0.0) >= safe_float(cue.get("start"), 0.0))
            )
        ]
        if not nearby:
            continue
        scored = [(score_style_event_for_cue(cue, ev, window_sec=match_window_sec), ev) for ev in nearby]
        scored.sort(key=lambda pair: (pair[0]["score"], pair[0]["overlap_score"], pair[0]["text_score"], -pair[0]["distance_sec"]), reverse=True)
        score_info, best_event = scored[0]
        if score_info["score"] < float(min_match_score):
            continue
        contract = build_event_style_contract(style_data, best_event, overrides=overrides)
        idx = safe_int(cue.get("index"), 0)
        if idx <= 0:
            continue
        cue_styles[idx] = contract
        profile_key = str(contract.get("profile_id") or contract.get("matched_style_profile_id") or "event_style")
        usage[profile_key] = usage.get(profile_key, 0) + 1
        if len(matches) < 12:
            matches.append({
                "cue_index": idx,
                "cue_id": cue.get("id"),
                "cue_text": cue.get("text"),
                "cue_start": cue.get("start"),
                "cue_end": cue.get("end"),
                "event_id": best_event.get("id"),
                "event_text": best_event.get("text"),
                "event_observed_text": best_event.get("observed_text"),
                "event_start": best_event.get("start"),
                "event_end": best_event.get("end"),
                "style_profile_id": contract.get("profile_id"),
                "match": score_info,
                "font_size_px": contract.get("font_size_px"),
                "fill": contract.get("fill"),
                "outline": contract.get("outline"),
                "anchor": contract.get("anchor"),
            })

    info["matched_cue_count"] = len(cue_styles)
    info["fallback_cue_count"] = max(0, len(cues) - len(cue_styles))
    info["style_profile_usage"] = dict(sorted(usage.items(), key=lambda kv: kv[1], reverse=True))
    info["first_matches"] = matches
    info["match_ratio"] = round(len(cue_styles) / max(1, len(cues)), 4)
    return cue_styles, info


def style_for_cue(cue: Dict[str, Any], base_style: Dict[str, Any], cue_styles: Optional[Dict[int, Dict[str, Any]]] = None) -> Dict[str, Any]:
    if not cue_styles:
        return base_style
    idx = safe_int(cue.get("index"), 0)
    return cue_styles.get(idx) or base_style


# -----------------------------------------------------------------------------
# Subtitle cue extraction
# -----------------------------------------------------------------------------


def find_first_list(data: Any, keys: Iterable[str]) -> Optional[List[Any]]:
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
        for value in data.values():
            found = find_first_list(value, keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = find_first_list(value, keys)
            if found is not None:
                return found
    return None


def extract_fps(generic: Dict[str, Any], fallback: float = 24.0) -> float:
    candidates = [
        read_nested(generic, [["meta", "fps"], ["timeline", "fps"], ["video", "fps"], ["project", "fps"], ["fps"]]),
        read_nested(generic, [["metadata", "fps"], ["source", "fps"]]),
    ]
    for value in candidates:
        fps = safe_float(value, 0.0)
        if fps > 0:
            return fps
    return fallback


def get_time_value(item: Dict[str, Any], names: Iterable[str], default: Optional[float] = None) -> Optional[float]:
    for name in names:
        if name in item and item[name] is not None:
            return safe_float(item[name], default if default is not None else 0.0)
    return default


def normalize_cue(raw: Dict[str, Any], index: int, fps: float) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None

    text = norm_text(raw.get("text") or raw.get("caption") or raw.get("word") or raw.get("content") or raw.get("label"))
    if not text:
        return None

    start = get_time_value(raw, ["start", "timeline_start", "source_start", "in", "from", "start_sec", "time_start"], None)
    end = get_time_value(raw, ["end", "timeline_end", "source_end", "out", "to", "end_sec", "time_end"], None)
    duration = get_time_value(raw, ["duration", "duration_sec"], None)

    start_frame = first_present(raw, ["start_frame", "timeline_start_frame", "frame_start"])
    end_frame = first_present(raw, ["end_frame", "timeline_end_frame", "frame_end"])
    duration_frames = first_present(raw, ["duration_frames", "frame_duration"])

    if start is None and start_frame is not None:
        start = safe_float(start_frame, 0.0) / fps
    if end is None and end_frame is not None:
        end = safe_float(end_frame, 0.0) / fps
    if duration is None and duration_frames is not None:
        duration = safe_float(duration_frames, 0.0) / fps

    if start is None:
        return None
    if end is None:
        end = start + (duration if duration is not None and duration > 0 else 0.5)
    if end <= start:
        end = start + (duration if duration is not None and duration > 0 else (1.0 / fps))

    return {
        "index": index,
        "id": raw.get("id") or raw.get("subtitle_id") or raw.get("cue_id") or f"sub_{index:04d}",
        "text": text,
        "start": round(float(start), 6),
        "end": round(float(end), 6),
        "duration": round(float(end - start), 6),
        "source": raw.get("source") or "generic_subtitle_clip",
        "raw": raw,
    }


def extract_subtitle_cues(generic: Dict[str, Any], source: str, fps: float) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    candidates: Optional[List[Any]] = None
    source_used = "unknown"

    if source in {"auto", "subtitle_clips"}:
        candidates = find_first_list(generic, ["subtitle_clips", "subtitles", "subtitle_cues", "captions", "caption_clips"])
        if candidates is not None:
            source_used = "subtitle_clips"

    if candidates is None and source in {"auto", "commands"}:
        command_lists = []
        for key in ("commands", "edit_commands", "operations", "timeline_commands"):
            value = generic.get(key)
            if isinstance(value, list):
                command_lists.extend(value)
        filtered = []
        for item in command_lists:
            if not isinstance(item, dict):
                continue
            typ = str(item.get("type") or item.get("action") or item.get("operation") or "").lower()
            if any(token in typ for token in ("subtitle", "caption", "text")):
                filtered.append(item)
        if filtered:
            candidates = filtered
            source_used = "commands_filtered"

    cues: List[Dict[str, Any]] = []
    if candidates:
        for i, raw in enumerate(candidates, start=1):
            cue = normalize_cue(raw, i, fps)
            if cue:
                cues.append(cue)

    return cues, {"source_requested": source, "source_used": source_used, "raw_candidates_count": len(candidates or [])}


def enforce_timing_rules(cues: List[Dict[str, Any]], fps: float, min_duration_frames: int, prevent_overlap: bool, max_cues: int = 0) -> List[Dict[str, Any]]:
    min_duration = max(1, int(min_duration_frames)) / fps
    ordered = sorted(cues, key=lambda c: (safe_float(c.get("start"), 0.0), safe_float(c.get("end"), 0.0)))
    if max_cues and max_cues > 0:
        ordered = ordered[:max_cues]

    out: List[Dict[str, Any]] = []
    for i, cue in enumerate(ordered):
        start = safe_float(cue.get("start"), 0.0)
        end = safe_float(cue.get("end"), start + min_duration)
        if end - start < min_duration:
            end = start + min_duration
        if prevent_overlap and out:
            prev = out[-1]
            prev_end = safe_float(prev.get("end"), 0.0)
            if start < prev_end:
                start = prev_end
                if end <= start:
                    end = start + min_duration
        cue2 = dict(cue)
        cue2["index"] = i + 1
        cue2["start"] = round(start, 6)
        cue2["end"] = round(end, 6)
        cue2["duration"] = round(end - start, 6)
        cue2["start_frame"] = sec_to_frames(start, fps)
        cue2["end_frame"] = sec_to_frames(end, fps)
        cue2["duration_frames"] = max(1, sec_to_frames(end, fps) - sec_to_frames(start, fps))
        out.append(cue2)
    return out


# -----------------------------------------------------------------------------
# Visual-first caption lifecycle support
# -----------------------------------------------------------------------------


def cue_transcript_window_frames(cue: Dict[str, Any], fps: float) -> List[int]:
    raw = cue.get("raw") if isinstance(cue.get("raw"), dict) else {}
    start = first_present(raw, ["timeline_start_frame", "start_frame", "frame_start"])
    end = first_present(raw, ["timeline_end_frame", "end_frame", "frame_end"])
    if start is None:
        start = cue.get("start_frame")
    if end is None:
        end = cue.get("end_frame")
    if start is None:
        start = sec_to_frames(safe_float(cue.get("start"), 0.0), fps)
    if end is None:
        end = sec_to_frames(safe_float(cue.get("end"), 0.0), fps)
    return [safe_int(start, 0), safe_int(end, 0)]


def normalize_semantic_caption_text(value: Any) -> str:
    text = norm_text(value).casefold().replace("’", "'")
    return re.sub(r"[^0-9a-zа-яё']+", "", text, flags=re.IGNORECASE)


def allocate_caption_lanes(cues: List[Dict[str, Any]], base_lane: int = 1) -> Dict[str, Any]:
    base_lane = max(1, int(base_lane))
    active: List[Tuple[int, int]] = []
    free_lanes: List[int] = []
    next_lane = base_lane
    usage: Dict[int, int] = {}
    max_concurrency = 0

    ordered = sorted(
        cues,
        key=lambda cue: (
            safe_int(cue.get("start_frame"), 0),
            safe_int(cue.get("end_frame"), 0),
            safe_int(cue.get("index"), 0),
        ),
    )
    for cue in ordered:
        start = safe_int(cue.get("start_frame"), 0)
        end = safe_int(cue.get("end_frame"), start + 1)
        while active and active[0][0] <= start:
            _, lane = heapq.heappop(active)
            heapq.heappush(free_lanes, lane)
        if free_lanes:
            lane = heapq.heappop(free_lanes)
        else:
            lane = next_lane
            next_lane += 1
        cue["lane"] = lane
        usage[lane] = usage.get(lane, 0) + 1
        heapq.heappush(active, (end, lane))
        max_concurrency = max(max_concurrency, len(active))

    return {
        "base_lane": base_lane,
        "max_lane": max(usage) if usage else base_lane,
        "lane_count": len(usage),
        "max_concurrency": max_concurrency,
        "lane_usage": {str(key): usage[key] for key in sorted(usage)},
    }


def apply_caption_lifecycle_plan(
    cues: List[Dict[str, Any]],
    plan: Dict[str, Any],
    fps: float,
    base_lane: int = 1,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not isinstance(plan, dict) or plan.get("ok") is not True:
        raise ValueError("caption_lifecycle_plan_not_ok")
    if plan.get("schema") != LIFECYCLE_PLAN_SCHEMA or safe_int(plan.get("schema_version"), 0) != 1:
        raise ValueError("caption_lifecycle_plan_schema")
    if plan.get("mandatory_visual_redetection_queue") not in ([], None):
        raise ValueError("caption_lifecycle_plan_redetection_queue_not_empty")

    raw_layers = plan.get("layers")
    if not isinstance(raw_layers, list):
        raise ValueError("caption_lifecycle_plan_layers")
    by_cue: Dict[str, Dict[str, Any]] = {}
    for layer in raw_layers:
        if not isinstance(layer, dict):
            raise ValueError("caption_lifecycle_plan_layer_type")
        cue_id = str(layer.get("cue_id") or "")
        if not cue_id or cue_id in by_cue:
            raise ValueError(f"caption_lifecycle_plan_duplicate_cue:{cue_id}")
        by_cue[cue_id] = layer

    cue_ids = [str(cue.get("id") or "") for cue in cues]
    if any(not cue_id for cue_id in cue_ids) or len(set(cue_ids)) != len(cue_ids):
        raise ValueError("caption_lifecycle_generic_duplicate_or_empty_cue")
    missing = [cue_id for cue_id in cue_ids if cue_id not in by_cue]
    unexpected = [cue_id for cue_id in by_cue if cue_id not in set(cue_ids)]
    if unexpected:
        raise ValueError("caption_lifecycle_plan_unexpected_cues:" + ",".join(unexpected[:10]))

    applied: List[Dict[str, Any]] = []
    timing_counts: Dict[str, int] = {}
    visual_outside_count = 0
    animated_count = 0
    animated_visual_count = 0
    generic_transcript_window_drift_count = 0
    generic_transcript_window_max_delta_frames = 0

    cue_index = 0
    merged_source_cue_count = 0
    missing_authority_fallback_ids: List[str] = []
    while cue_index < len(cues):
        cue = cues[cue_index]
        cue_id = str(cue.get("id") or "")
        generic_transcript_window = cue_transcript_window_frames(cue, fps)
        layer = by_cue.get(cue_id)
        source_cues = [cue]
        if layer is not None:
            group_end = cue_index + 1
            while group_end < len(cues) and str(cues[group_end].get("id") or "") not in by_cue:
                group_end += 1
            candidates = cues[cue_index:group_end]
            candidate_text = " ".join(norm_text(row.get("text")) for row in candidates)
            if len(candidates) > 1 and normalize_semantic_caption_text(layer.get("text")) == normalize_semantic_caption_text(candidate_text):
                source_cues = candidates
                generic_transcript_window = [
                    cue_transcript_window_frames(source_cues[0], fps)[0],
                    cue_transcript_window_frames(source_cues[-1], fps)[1],
                ]
                merged_source_cue_count += len(source_cues) - 1
        if layer is None:
            missing_authority_fallback_ids.append(cue_id)
        layer = layer or {
            "cue_id": cue_id,
            "text": cue.get("text"),
            "transcript_window": generic_transcript_window,
            "lifecycle_window": generic_transcript_window,
            "timing_authority": "transcript_fallback",
            "lifecycle_status": "authority_row_missing_transcript_fallback",
            "lifecycle_phases": [],
            "opacity_envelope": None,
            "animation_selected_step_3C": False,
            "animation_type_step_3C": None,
            "visual_confidence_label": None,
        }
        layer_transcript = layer.get("transcript_window")
        if (
            not isinstance(layer_transcript, list)
            or len(layer_transcript) != 2
            or safe_int(layer_transcript[1], 0) <= safe_int(layer_transcript[0], 0)
        ):
            raise ValueError(f"caption_lifecycle_transcript_window:{cue_id}")
        transcript_window = [safe_int(layer_transcript[0], 0), safe_int(layer_transcript[1], 0)]
        deltas = [
            abs(transcript_window[0] - generic_transcript_window[0]),
            abs(transcript_window[1] - generic_transcript_window[1]),
        ]
        if any(deltas):
            generic_transcript_window_drift_count += 1
            generic_transcript_window_max_delta_frames = max(
                generic_transcript_window_max_delta_frames, max(deltas)
            )
        lifecycle = layer.get("lifecycle_window")
        if (
            not isinstance(lifecycle, list)
            or len(lifecycle) != 2
            or safe_int(lifecycle[1], 0) <= safe_int(lifecycle[0], 0)
        ):
            raise ValueError(f"caption_lifecycle_window:{cue_id}")
        timing_authority = str(layer.get("timing_authority") or "")
        if timing_authority not in LIFECYCLE_TIMING_AUTHORITIES:
            raise ValueError(f"caption_lifecycle_timing_authority:{cue_id}:{timing_authority}")
        if timing_authority == "transcript_fallback" and lifecycle != transcript_window:
            raise ValueError(f"caption_lifecycle_fallback_window:{cue_id}")

        transcript_text = " ".join(norm_text(row.get("text")) for row in source_cues)
        display_text = norm_text(layer.get("text")) or transcript_text
        if normalize_semantic_caption_text(display_text) != normalize_semantic_caption_text(transcript_text):
            raise ValueError(f"caption_lifecycle_text_mismatch:{cue_id}:{display_text}:{transcript_text}")

        start_frame = safe_int(lifecycle[0], 0)
        end_frame = safe_int(lifecycle[1], start_frame + 1)
        updated = dict(cue)
        updated.update({
            "text": display_text,
            "transcript_text": transcript_text,
            "transcript_window": transcript_window,
            "generic_transcript_window": generic_transcript_window,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "duration_frames": end_frame - start_frame,
            "start": round(start_frame / fps, 6),
            "end": round(end_frame / fps, 6),
            "duration": round((end_frame - start_frame) / fps, 6),
            "timing_authority": timing_authority,
            "lifecycle_status": layer.get("lifecycle_status"),
            "lifecycle_phases": layer.get("lifecycle_phases"),
            "opacity_envelope": layer.get("opacity_envelope"),
            "animation_selected_step_3C": bool(layer.get("animation_selected_step_3C")),
            "animation_type_step_3C": layer.get("animation_type_step_3C"),
            "visual_confidence_label": layer.get("visual_confidence_label"),
            "semantic_source_cue_ids": [str(row.get("id") or "") for row in source_cues],
        })
        applied.append(updated)
        timing_counts[timing_authority] = timing_counts.get(timing_authority, 0) + 1
        if lifecycle != transcript_window:
            visual_outside_count += 1
        if updated["animation_selected_step_3C"]:
            animated_count += 1
            if timing_authority.startswith("visual_primary"):
                animated_visual_count += 1
        cue_index += len(source_cues)

    lane_info = allocate_caption_lanes(applied, base_lane=base_lane)
    summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
    info = {
        "enabled": True,
        "schema": plan.get("schema"),
        "schema_version": plan.get("schema_version"),
        "version": plan.get("version"),
        "authority_policy": plan.get("authority_policy"),
        "plan_semantic_sha256": canonical_json_sha256(plan),
        "layer_count": len(applied),
        "timing_authority_counts": dict(sorted(timing_counts.items())),
        "visual_primary_count": timing_counts.get("visual_primary", 0) + timing_counts.get("visual_primary_redetected", 0),
        "transcript_fallback_count": timing_counts.get("transcript_fallback", 0),
        "lifecycle_differs_from_transcript_count": visual_outside_count,
        "animated_caption_count": animated_count,
        "animated_visual_lifecycle_count": animated_visual_count,
        "mandatory_redetection_count": len(plan.get("mandatory_visual_redetection_queue") or []),
        "missing_authority_fallback_count": len(missing_authority_fallback_ids),
        "missing_authority_fallback_cue_ids": missing_authority_fallback_ids,
        "source_cue_ids_absent_from_plan": missing,
        "merged_source_cue_count": merged_source_cue_count,
        "source_summary": summary,
        "lane_allocation": lane_info,
        "overlap_preserved": True,
        "transcript_text_semantics_preserved": True,
        "display_casing_from_calibrated_plan": True,
        "generic_transcript_window_drift_count": generic_transcript_window_drift_count,
        "generic_transcript_window_max_delta_frames": generic_transcript_window_max_delta_frames,
        "generic_timing_role": "identity_fallback_only; calibrated plan owns emitted caption timing",
    }
    return applied, info


# -----------------------------------------------------------------------------
# Video clip extraction for full_timeline mode
# -----------------------------------------------------------------------------


def is_probably_text_item(item: Dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return False
    if any(k in item for k in ("text", "caption", "word", "content", "subtitle_id", "cue_id")):
        typ = str(item.get("type") or item.get("action") or item.get("operation") or "").lower()
        # Keep true video operations even if they contain labels/notes.
        if not any(t in typ for t in ("video", "clip", "cut", "shot")):
            return True
    return False


def video_item_score(item: Dict[str, Any]) -> int:
    if not isinstance(item, dict) or is_probably_text_item(item):
        return 0
    keys = set(item.keys())
    score = 0
    for k in ("source_start", "source_end", "source_duration", "source_in", "source_out", "source_start_frame", "source_end_frame", "source_in_frame", "source_out_frame"):
        if k in keys:
            score += 3
    for k in ("timeline_start", "timeline_end", "timeline_duration", "timeline_start_frame", "timeline_end_frame", "start_frame", "end_frame"):
        if k in keys:
            score += 2
    typ = str(item.get("type") or item.get("action") or item.get("operation") or item.get("kind") or "").lower()
    if any(t in typ for t in ("video", "clip", "cut", "shot", "asset")):
        score += 3
    if any(k in keys for k in ("shot_id", "clip_id", "media_path", "video_path", "source_path")):
        score += 2
    return score


def collect_candidate_lists(data: Any, path: str = "") -> List[Tuple[str, List[Dict[str, Any]], int]]:
    out: List[Tuple[str, List[Dict[str, Any]], int]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            out.extend(collect_candidate_lists(value, f"{path}.{key}" if path else key))
    elif isinstance(data, list):
        dict_items = [x for x in data if isinstance(x, dict)]
        if dict_items:
            scores = [video_item_score(x) for x in dict_items]
            good = [x for x, s in zip(dict_items, scores) if s >= 5]
            total_score = sum(scores)
            if len(good) >= 1 and total_score > 0:
                out.append((path, good, total_score))
        for i, value in enumerate(data[:10]):
            # Recurse only shallowly into first few items to avoid pathological scans.
            out.extend(collect_candidate_lists(value, f"{path}[{i}]"))
    return out


def normalize_video_clip(raw: Dict[str, Any], index: int, fps: float) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict) or is_probably_text_item(raw):
        return None

    source_start = get_time_value(raw, ["source_start", "source_in", "media_start", "in", "clip_source_start"], None)
    source_end = get_time_value(raw, ["source_end", "source_out", "media_end", "out", "clip_source_end"], None)
    source_duration = get_time_value(raw, ["source_duration", "media_duration", "clip_source_duration"], None)

    timeline_start = get_time_value(raw, ["timeline_start", "target_start", "record_start", "start", "time_start"], None)
    timeline_end = get_time_value(raw, ["timeline_end", "target_end", "record_end", "end", "time_end"], None)
    timeline_duration = get_time_value(raw, ["timeline_duration", "duration", "duration_sec"], None)

    source_start_frame = first_present(raw, ["source_start_frame", "source_in_frame"])
    source_end_frame = first_present(raw, ["source_end_frame", "source_out_frame"])
    timeline_start_frame = first_present(raw, ["timeline_start_frame", "start_frame"])
    timeline_end_frame = first_present(raw, ["timeline_end_frame", "end_frame"])
    duration_frames = first_present(raw, ["duration_frames", "timeline_duration_frames"])

    if source_start is None and source_start_frame is not None:
        source_start = safe_float(source_start_frame, 0.0) / fps
    if source_end is None and source_end_frame is not None:
        source_end = safe_float(source_end_frame, 0.0) / fps
    if timeline_start is None and timeline_start_frame is not None:
        timeline_start = safe_float(timeline_start_frame, 0.0) / fps
    if timeline_end is None and timeline_end_frame is not None:
        timeline_end = safe_float(timeline_end_frame, 0.0) / fps
    if timeline_duration is None and duration_frames is not None:
        timeline_duration = safe_float(duration_frames, 0.0) / fps

    if source_start is None:
        # If only generic start/end are available, assume source starts at same value.
        source_start = 0.0 if timeline_start is None else safe_float(raw.get("source_start", 0.0), 0.0)

    if source_end is None:
        if source_duration is not None and source_duration > 0:
            source_end = source_start + source_duration
        elif timeline_duration is not None and timeline_duration > 0:
            source_end = source_start + timeline_duration
        elif timeline_end is not None and timeline_start is not None and timeline_end > timeline_start:
            source_end = source_start + (timeline_end - timeline_start)
        else:
            source_end = source_start + 0.5

    if timeline_duration is None:
        if timeline_end is not None and timeline_start is not None and timeline_end > timeline_start:
            timeline_duration = timeline_end - timeline_start
        else:
            timeline_duration = max(1.0 / fps, source_end - source_start)

    if timeline_start is None:
        # Sequential placement will be filled later.
        timeline_start = None
    if timeline_end is None and timeline_start is not None:
        timeline_end = timeline_start + timeline_duration

    name = raw.get("name") or raw.get("id") or raw.get("clip_id") or raw.get("shot_id") or f"VC_OP_{index:03d}_cut"
    media_path = raw.get("media_path") or raw.get("video_path") or raw.get("source_path") or raw.get("path")

    return {
        "index": index,
        "id": raw.get("id") or raw.get("clip_id") or raw.get("shot_id") or f"video_{index:04d}",
        "name": str(name),
        "source_start": round(float(source_start), 6),
        "source_end": round(float(source_end), 6),
        "source_duration": round(float(source_end - source_start), 6),
        "timeline_start": None if timeline_start is None else round(float(timeline_start), 6),
        "timeline_end": None if timeline_end is None else round(float(timeline_end), 6),
        "timeline_duration": round(float(max(1.0 / fps, timeline_duration)), 6),
        "media_path": media_path,
        "raw": raw,
    }


def extract_video_clips(generic: Dict[str, Any], fps: float, total_duration_hint: float) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    candidates = collect_candidate_lists(generic)
    # Strong preference for obvious clip/video paths; otherwise choose highest score.
    preferred_tokens = ("video_clip", "video_clips", "timeline_clips", "clips", "edit_clips", "cuts", "shots")
    candidates.sort(key=lambda x: (any(tok in x[0].lower() for tok in preferred_tokens), x[2], len(x[1])), reverse=True)

    source_path = None
    raw_list: List[Dict[str, Any]] = []
    selected_path = None
    selected_score = 0
    if candidates:
        selected_path, raw_list, selected_score = candidates[0]

    clips: List[Dict[str, Any]] = []
    for i, raw in enumerate(raw_list, start=1):
        clip = normalize_video_clip(raw, i, fps)
        if clip:
            clips.append(clip)

    # Remove obvious accidental full subtitle/marker lists.
    clips = [c for c in clips if c.get("timeline_duration", 0) > 0]

    # Fill missing timeline starts sequentially and convert to frames.
    current = 0.0
    out: List[Dict[str, Any]] = []
    for i, clip in enumerate(sorted(clips, key=lambda c: (float("inf") if c.get("timeline_start") is None else c.get("timeline_start"), c.get("index", 0))), start=1):
        c = dict(clip)
        if c.get("timeline_start") is None:
            c["timeline_start"] = round(current, 6)
        if c.get("timeline_end") is None:
            c["timeline_end"] = round(c["timeline_start"] + c["timeline_duration"], 6)
        c["timeline_duration"] = round(max(1.0 / fps, c["timeline_end"] - c["timeline_start"]), 6)
        c["timeline_start_frame"] = sec_to_frames(c["timeline_start"], fps)
        c["timeline_end_frame"] = sec_to_frames(c["timeline_end"], fps)
        c["timeline_duration_frames"] = max(1, c["timeline_end_frame"] - c["timeline_start_frame"])
        c["source_start_frame"] = sec_to_frames(c["source_start"], fps)
        c["source_duration_frames"] = max(1, sec_to_frames(c["source_duration"], fps))
        c["index"] = i
        current = max(current, safe_float(c.get("timeline_end"), current))
        out.append(c)

    if not out:
        # Safe fallback: one continuous clip. This still creates a usable full timeline,
        # but report warns that actual cuts were not reconstructed from generic JSON.
        dur = max(1.0 / fps, total_duration_hint)
        out = [{
            "index": 1,
            "id": "video_fallback_full_length",
            "name": "VC_full_length_video_fallback",
            "source_start": 0.0,
            "source_end": round(dur, 6),
            "source_duration": round(dur, 6),
            "timeline_start": 0.0,
            "timeline_end": round(dur, 6),
            "timeline_duration": round(dur, 6),
            "timeline_start_frame": 0,
            "timeline_end_frame": sec_to_frames(dur, fps),
            "timeline_duration_frames": max(1, sec_to_frames(dur, fps)),
            "source_start_frame": 0,
            "source_duration_frames": max(1, sec_to_frames(dur, fps)),
            "media_path": None,
            "raw": {},
        }]

    return out, {
        "selected_candidate_path": selected_path,
        "selected_candidate_score": selected_score,
        "candidate_lists_found": len(candidates),
        "video_clips_extracted": len(out),
        "fallback_continuous_clip": bool(not clips),
    }



# -----------------------------------------------------------------------------
# Transition extraction for full_timeline mode
# -----------------------------------------------------------------------------


def confidence_value(value: Any) -> int:
    if isinstance(value, (int, float)):
        # Numeric scores are normalized onto a 0..5-ish ladder.
        v = float(value)
        if v >= 0.85:
            return CONFIDENCE_RANK["very_high"]
        if v >= 0.65:
            return CONFIDENCE_RANK["high"]
        if v >= 0.45:
            return CONFIDENCE_RANK["medium"]
        if v > 0:
            return CONFIDENCE_RANK["low"]
        return CONFIDENCE_RANK["none"]
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return CONFIDENCE_RANK.get(text, CONFIDENCE_RANK["none"])


def confidence_label(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip().lower().replace("-", "_").replace(" ", "_")
    score = confidence_value(value)
    for k, v in CONFIDENCE_RANK.items():
        if v == score:
            return k
    return "none"


def normalize_transition_type_text(raw_type: Any) -> str:
    return str(raw_type or "").strip().lower().replace("-", "_").replace(" ", "_")


def transition_type_to_effect_key(raw_type: Any, fallback_mode: str = "mapped") -> str:
    text = normalize_transition_type_text(raw_type)
    if fallback_mode == "cross_dissolve":
        return "cross_dissolve"
    if any(t in text for t in ("slide", "push", "swipe")):
        return "slide"
    if any(t in text for t in ("wipe", "reveal")):
        return "wipe"
    if any(t in text for t in ("fade", "dip_to_color", "fade_to_color")):
        return "fade_to_color"
    if any(t in text for t in ("dissolve", "blend", "opacity", "cross")):
        return "cross_dissolve"
    return "cross_dissolve"


def transition_type_to_backend(raw_type: Any, transition_mode: str = "hybrid") -> str:
    mode = str(transition_mode or "hybrid").strip().lower()
    text = normalize_transition_type_text(raw_type)
    if mode == "none":
        return "none"
    if mode == "native":
        return "native"
    if mode in {"vfx", "vfx_placeholder", "vfx_placeholders"}:
        return "vfx_placeholder"
    if any(token in text for token in VFX_TRANSITION_KEYWORDS):
        return "vfx_placeholder"
    if any(token in text for token in CUT_ONLY_TRANSITION_KEYWORDS):
        return "cut_only"
    if any(token in text for token in NATIVE_TRANSITION_KEYWORDS):
        return "native"
    return "vfx_placeholder"


def build_transition_effect_profile(transition_type: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    text = normalize_transition_type_text(transition_type)
    profile: Dict[str, Any] = {
        "transition_type": str(transition_type or "transition_hint"),
        "backend": "vfx_placeholder",
        "effect_family": "generic_vfx_transition",
        "needs_resolve_controller": True,
        "parameters": {},
    }
    if "blur" in text or "lens" in text:
        profile["effect_family"] = "blur_zoom_transition"
        profile["parameters"].update({"blur_peak": 24, "zoom_peak": 1.12})
    elif "whip" in text or "pan" in text:
        profile["effect_family"] = "whip_pan_transition"
        profile["parameters"].update({"motion_blur": True, "direction": params.get("direction") or "auto"})
    elif "flash" in text or "light" in text or "flare" in text or "glow" in text:
        profile["effect_family"] = "flash_or_light_leak_transition"
        profile["parameters"].update({"flash_color": params.get("flash_color") or "#ffffff", "peak_opacity": 0.75})
    elif "zoom" in text:
        profile["effect_family"] = "zoom_transition"
        profile["parameters"].update({"zoom_peak": 1.16})
    elif "shake" in text or "impact" in text:
        profile["effect_family"] = "camera_shake_transition"
        profile["parameters"].update({"shake_strength": params.get("strength") or "auto"})
    for key in (
        "strength", "confidence", "duration_frames", "duration_seconds", "outgoing_frames", "incoming_frames",
        "cut_frame", "timeline_cut_frame", "cut_time", "timeline_cut_seconds", "direction", "side", "placement"
    ):
        if key in params:
            profile["parameters"][key] = params.get(key)
    return profile


def is_transition_hint_dict(item: Dict[str, Any]) -> bool:
    typ = str(item.get("operation") or item.get("type") or item.get("action") or item.get("kind") or "").strip().lower()
    if typ == "transition_hint" or typ.endswith(".transition_hint"):
        return True
    params = item.get("parameters") if isinstance(item.get("parameters"), dict) else item
    if not isinstance(params, dict):
        return False
    if any(k in params for k in ("transition_type", "transition", "timeline_cut_frame", "cut_frame", "cut_time")):
        text = str(params.get("transition_type") or params.get("transition") or typ).lower()
        return "transition" in text or "cut_frame" in params or "timeline_cut_frame" in params
    return False


def collect_transition_hint_dicts(data: Any, path: str = "", seen: Optional[set] = None) -> List[Tuple[str, Dict[str, Any]]]:
    seen = seen if seen is not None else set()
    out: List[Tuple[str, Dict[str, Any]]] = []
    if isinstance(data, dict):
        obj_id = id(data)
        if obj_id not in seen and is_transition_hint_dict(data):
            seen.add(obj_id)
            out.append((path or "$", data))
        for key, value in data.items():
            child_path = f"{path}.{key}" if path else str(key)
            out.extend(collect_transition_hint_dicts(value, child_path, seen))
    elif isinstance(data, list):
        for i, value in enumerate(data):
            out.extend(collect_transition_hint_dicts(value, f"{path}[{i}]", seen))
    return out


def nearest_video_cut_boundary(cut_frame: int, video_clips: List[Dict[str, Any]], tolerance_frames: int) -> Optional[Dict[str, Any]]:
    boundaries: List[Dict[str, Any]] = []
    ordered = sorted(video_clips, key=lambda c: safe_int(c.get("timeline_start_frame"), 0))
    for i, clip in enumerate(ordered[:-1], start=1):
        frame = safe_int(clip.get("timeline_end_frame"), 0)
        next_clip = ordered[i] if i < len(ordered) else None
        boundaries.append({
            "frame": frame,
            "outgoing_index": safe_int(clip.get("index"), i),
            "incoming_index": safe_int(next_clip.get("index"), i + 1) if next_clip else None,
            "outgoing_name": clip.get("name"),
            "incoming_name": next_clip.get("name") if next_clip else None,
        })
    if not boundaries:
        return None
    best = min(boundaries, key=lambda b: abs(safe_int(b.get("frame"), 0) - cut_frame))
    delta = abs(safe_int(best.get("frame"), 0) - cut_frame)
    if delta <= max(0, int(tolerance_frames)):
        out = dict(best)
        out["requested_frame"] = cut_frame
        out["delta_frames"] = delta
        return out
    return None


def normalize_transition_hint(
    raw: Dict[str, Any],
    index: int,
    fps: float,
    video_clips: List[Dict[str, Any]],
    min_confidence: str,
    default_duration_frames: int,
    max_duration_frames: int,
    boundary_tolerance_frames: int,
    require_handles: bool,
    effect_fallback_mode: str,
    transition_mode: str = "hybrid",
) -> Optional[Dict[str, Any]]:
    params = raw.get("parameters") if isinstance(raw.get("parameters"), dict) else raw
    if not isinstance(params, dict):
        return None

    confidence_raw = params.get("confidence", raw.get("confidence", raw.get("transition_to_next_confidence")))
    if confidence_raw is None:
        confidence_raw = params.get("score", raw.get("score"))
    confidence = confidence_label(confidence_raw)
    if str(min_confidence).lower() != "any" and confidence_value(confidence_raw) < confidence_value(min_confidence):
        return None

    cut_frame = None
    for key in ("timeline_cut_frame", "cut_frame", "cutFrame", "timeline_cut", "frame"):
        if params.get(key) is not None:
            cut_frame = safe_int(params.get(key), 0)
            break
    if cut_frame is None:
        for key in ("cut_time", "timeline_cut_seconds", "cut_seconds", "time"):
            if params.get(key) is not None:
                cut_frame = sec_to_frames(safe_float(params.get(key), 0.0), fps)
                break
    if cut_frame is None:
        return None

    boundary = nearest_video_cut_boundary(cut_frame, video_clips, tolerance_frames=boundary_tolerance_frames)
    if not boundary:
        return None

    duration_frames = None
    for key in ("duration_frames", "transition_duration_frames"):
        if params.get(key) is not None:
            duration_frames = safe_int(params.get(key), default_duration_frames)
            break
    if duration_frames is None:
        for key in ("duration_seconds", "transition_duration_seconds", "duration"):
            if params.get(key) is not None:
                duration_frames = sec_to_frames(safe_float(params.get(key), default_duration_frames / fps), fps)
                break
    if duration_frames is None or duration_frames <= 0:
        duration_frames = max(1, int(default_duration_frames))

    outgoing_frames = safe_int(params.get("outgoing_frames") or params.get("required_outgoing_handle_frames"), max(1, duration_frames // 2))
    incoming_frames = safe_int(params.get("incoming_frames") or params.get("required_incoming_handle_frames"), max(1, duration_frames - outgoing_frames))
    available_out = safe_int(params.get("available_outgoing_handle_frames"), outgoing_frames)
    available_in = safe_int(params.get("available_incoming_handle_frames"), incoming_frames)
    has_handles = bool(params.get("has_required_handles", True))

    if require_handles and not has_handles:
        return None

    # Keep transitions within the reported/available handles. A centered transition
    # uses outgoing+incoming frames. If only one side is reported, default split works.
    max_by_handles = max(1, min(max_duration_frames, available_out + available_in))
    duration_frames = max(1, min(int(duration_frames), int(max_duration_frames), int(max_by_handles)))

    transition_type = params.get("transition_type") or params.get("type") or raw.get("transition_type") or "transition_hint"
    backend = transition_type_to_backend(transition_type, transition_mode=transition_mode)
    effect_key = transition_type_to_effect_key(transition_type, fallback_mode=effect_fallback_mode)
    effect = TRANSITION_EFFECTS.get(effect_key, TRANSITION_EFFECTS["cross_dissolve"])
    effect_profile = build_transition_effect_profile(transition_type, params)

    boundary_frame = safe_int(boundary.get("frame"), cut_frame)
    # FCPXML transition offset is placed at the start of the transition region.
    # For the handle model from analysis, outgoing_frames typically equals half.
    offset_frame = max(0, boundary_frame - min(outgoing_frames, duration_frames // 2 if duration_frames > 1 else 0))

    return {
        "index": index,
        "id": raw.get("id") or raw.get("transition_id") or f"transition_{index:04d}",
        "transition_type": transition_type,
        "backend": backend,
        "effect_profile": effect_profile,
        "confidence": confidence,
        "confidence_raw": confidence_raw,
        "strength": safe_float(params.get("strength"), safe_float(params.get("score"), 0.0)),
        "requested_cut_frame": cut_frame,
        "boundary_frame": boundary_frame,
        "boundary_delta_frames": safe_int(boundary.get("delta_frames"), 0),
        "offset_frame": offset_frame,
        "duration_frames": max(1, int(duration_frames)),
        "outgoing_frames": outgoing_frames,
        "incoming_frames": incoming_frames,
        "effect_key": effect_key,
        "effect_name": effect["name"],
        "effect_uid": effect["uid"],
        "boundary": boundary,
        "raw_parameters": params,
    }


def extract_transition_hints(
    generic: Dict[str, Any],
    fps: float,
    video_clips: List[Dict[str, Any]],
    include_transitions: bool,
    transition_mode: str,
    min_confidence: str,
    default_duration_frames: int,
    max_duration_frames: int,
    boundary_tolerance_frames: int,
    require_handles: bool,
    effect_fallback_mode: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    raw_items = collect_transition_hint_dicts(generic)
    info: Dict[str, Any] = {
        "include_transitions": bool(include_transitions),
        "transition_mode": transition_mode,
        "raw_transition_hint_count": len(raw_items),
        "min_confidence": min_confidence,
        "default_duration_frames": default_duration_frames,
        "max_duration_frames": max_duration_frames,
        "boundary_tolerance_frames": boundary_tolerance_frames,
        "require_handles": bool(require_handles),
        "effect_fallback_mode": effect_fallback_mode,
        "skipped_reason": None,
    }
    if not include_transitions or str(transition_mode).lower() == "none":
        info["skipped_reason"] = "disabled"
        return [], info
    if len(video_clips) < 2:
        info["skipped_reason"] = "not_enough_video_clips"
        return [], info

    normalized: List[Dict[str, Any]] = []
    for i, (path, raw) in enumerate(raw_items, start=1):
        t = normalize_transition_hint(
            raw=raw,
            index=i,
            fps=fps,
            video_clips=video_clips,
            min_confidence=min_confidence,
            default_duration_frames=max(1, default_duration_frames),
            max_duration_frames=max(1, max_duration_frames),
            boundary_tolerance_frames=max(0, boundary_tolerance_frames),
            require_handles=require_handles,
            effect_fallback_mode=effect_fallback_mode,
            transition_mode=transition_mode,
        )
        if t:
            t["source_path"] = path
            normalized.append(t)

    # De-dupe: one native transition per edit point. Keep strongest/highest-confidence.
    by_boundary: Dict[int, Dict[str, Any]] = {}
    for t in normalized:
        key = safe_int(t.get("boundary_frame"), -1)
        old = by_boundary.get(key)
        if old is None:
            by_boundary[key] = t
            continue
        old_score = (confidence_value(old.get("confidence_raw")), safe_float(old.get("strength"), 0.0), safe_int(old.get("duration_frames"), 0))
        new_score = (confidence_value(t.get("confidence_raw")), safe_float(t.get("strength"), 0.0), safe_int(t.get("duration_frames"), 0))
        if new_score > old_score:
            by_boundary[key] = t

    transitions = sorted(by_boundary.values(), key=lambda x: safe_int(x.get("boundary_frame"), 0))
    for i, t in enumerate(transitions, start=1):
        t["index"] = i
    info.update({
        "normalized_transition_count": len(normalized),
        "deduped_transition_count": len(transitions),
        "backend_counts": {k: sum(1 for t in transitions if t.get("backend") == k) for k in sorted({t.get("backend") for t in transitions})},
        "effect_counts": {k: sum(1 for t in transitions if t.get("effect_key") == k) for k in sorted({t.get("effect_key") for t in transitions if t.get("backend") == "native"})},
        "first_transition": {k: transitions[0].get(k) for k in ("index", "transition_type", "backend", "confidence", "boundary_frame", "duration_frames", "effect_key", "effect_name")} if transitions else None,
    })
    return transitions, info


def build_transition_resources(transitions: List[Dict[str, Any]], start_index: int = 5) -> Tuple[str, Dict[str, str]]:
    used_keys: List[str] = []
    for t in transitions:
        if str(t.get("backend") or "native") != "native":
            continue
        key = str(t.get("effect_key") or "cross_dissolve")
        if key not in used_keys:
            used_keys.append(key)
    resource_ids: Dict[str, str] = {}
    lines: List[str] = []
    for i, key in enumerate(used_keys, start=start_index):
        effect = TRANSITION_EFFECTS.get(key, TRANSITION_EFFECTS["cross_dissolve"])
        rid = f"r{i}"
        resource_ids[key] = rid
        lines.append(f'    <effect id="{rid}" name="{xml_escape(effect["name"])}" uid="{xml_escape(effect["uid"])}"/>')
    return "\n".join(lines), resource_ids


def build_transition_xml(transition: Dict[str, Any], effect_ref: str, fps: float, indent: str = "        ") -> str:
    name = xml_escape(transition.get("effect_name") or "Cross Dissolve")
    offset = frames_to_fcpx_time(safe_int(transition.get("offset_frame"), 0), fps)
    duration = frames_to_fcpx_time(max(1, safe_int(transition.get("duration_frames"), 1)), fps)
    # Keep the element simple. Resolve either imports it as a native transition or
    # ignores it; the report remains the source of truth for unsupported cases.
    return f'{indent}<transition name="{name}" ref="{effect_ref}" offset="{offset}" duration="{duration}"/>'


def build_vfx_placeholder_xml(
    transition: Dict[str, Any],
    effect_ref: str,
    fps: float,
    lane: int = 2,
    visible: bool = False,
    prefix: str = "VC VFX Transition",
    indent: str = "        ",
) -> str:
    idx = safe_int(transition.get("index"), 1)
    transition_type = str(transition.get("transition_type") or "vfx_transition")
    safe_type = re.sub(r"[^A-Za-z0-9_]+", "_", normalize_transition_type_text(transition_type)).strip("_") or "vfx"
    name = xml_escape(f"VC_VFX_{idx:03d}_{safe_type}")
    offset_frames = safe_int(transition.get("offset_frame"), safe_int(transition.get("boundary_frame"), 0))
    duration_frames = max(1, safe_int(transition.get("duration_frames"), 1))
    offset = frames_to_fcpx_time(offset_frames, fps)
    duration = frames_to_fcpx_time(duration_frames, fps)
    ts_id = f"vfx_ts{idx}"
    marker_payload = {
        "schema": "video_cloner_transition_vfx_placeholder",
        "schema_version": "1.0",
        "transition_id": transition.get("id"),
        "transition_type": transition_type,
        "backend": transition.get("backend"),
        "effect_profile": transition.get("effect_profile"),
        "boundary_frame": transition.get("boundary_frame"),
        "offset_frame": transition.get("offset_frame"),
        "duration_frames": transition.get("duration_frames"),
        "confidence": transition.get("confidence"),
        "strength": transition.get("strength"),
    }
    note = xml_escape(json.dumps(marker_payload, ensure_ascii=False, separators=(",", ":")))
    marker_value = xml_escape(f"{prefix} {idx:03d}: {transition_type}")
    if visible:
        display_text = xml_escape(f"VFX {idx}: {transition_type}")
        style_attrs = 'font="Arial" fontSize="28" fontColor="1 0.85 0 1" bold="1" italic="0" alignment="center" strokeColor="0 0 0 1" strokeWidth="2"'
    else:
        display_text = " "
        style_attrs = 'font="Arial" fontSize="1" fontColor="0 0 0 0" bold="0" italic="0" alignment="center" strokeColor="0 0 0 0" strokeWidth="0" shadowColor="0 0 0 0" shadowOffset="0" shadowBlurRadius="0"'
    return f"""{indent}<title ref="{effect_ref}" name="{name}" lane="{lane}" offset="{offset}" start="0s" duration="{duration}">
{indent}  <marker start="0s" duration="{duration}" value="{marker_value}" note="{note}"/>
{indent}  <adjust-transform position="0.000 0.000" anchor="0 0" scale="1 1"/>
{indent}  <text>
{indent}    <text-style ref="{ts_id}">{display_text}</text-style>
{indent}  </text>
{indent}  <text-style-def id="{ts_id}">
{indent}    <text-style {style_attrs}/>
{indent}  </text-style-def>
{indent}</title>"""


def build_vfx_placeholders_xml(
    transitions: List[Dict[str, Any]],
    effect_ref: str,
    fps: float,
    lane: int = 2,
    visible: bool = False,
    prefix: str = "VC VFX Transition",
) -> str:
    lines = []
    for transition in transitions or []:
        if str(transition.get("backend") or "") != "vfx_placeholder":
            continue
        lines.append(build_vfx_placeholder_xml(transition, effect_ref=effect_ref, fps=fps, lane=lane, visible=visible, prefix=prefix))
    return "\n".join(lines)

# -----------------------------------------------------------------------------
# FCPXML builder
# -----------------------------------------------------------------------------


# Resolve 21 Basic Title importer uses a different font-size unit from our
# OCR/Editing-DNA pixel heights.  In an isolated 1080x1920 title-only render,
# the two unobstructed Arial Bold samples gave consistent ratios:
#   why:     326 rendered px / 190 nominal px = 1.716
#   telling: 886 rendered px / 518 nominal px = 1.710
# Calibrate the *output adapter*, never the detected source font-height data.
# This value describes the current Resolve 21 Basic Title 1080x1920 profile;
# other renderer profiles need their own native measurement before reuse.
RESOLVE21_BASIC_TITLE_RENDER_PX_PER_FCPXML_FONT_UNIT = 1.71


def fcpxml_text_style_attrs(style: Dict[str, Any]) -> str:
    alignment = str(style.get("alignment") or "").strip().lower()
    font_height_px = float(style["font_size_px"])
    if not math.isfinite(font_height_px) or font_height_px <= 0:
        raise ValueError("Basic Title font height must be positive and finite")
    calibrated_units = max(1, round(font_height_px / RESOLVE21_BASIC_TITLE_RENDER_PX_PER_FCPXML_FONT_UNIT))
    attrs = {
        "font": style["font_name"],
        "fontSize": str(calibrated_units),
        "fontColor": style["fill_fcpxml"],
        "bold": "1" if style.get("bold") else "0",
        "italic": "1" if style.get("italic") else "0",
        "alignment": alignment if alignment in {"left", "center", "right"} else "center",
        "strokeColor": style["outline_fcpxml"],
        "strokeWidth": str(style["outline_px"]),
        "shadowColor": style["shadow_fcpxml"],
        "shadowOffset": str(style["shadow_px"]),
        "shadowBlurRadius": str(max(0.0, safe_float(style.get("shadow_px"), 2.0))),
    }
    return " ".join(f'{k}=\"{xml_escape(v)}\"' for k, v in attrs.items())


def compute_position(style: Dict[str, Any], width: int, height: int, position_mode: str, position_x: float, position_y: float) -> Tuple[float, float, str]:
    ax = safe_float((style.get("anchor") or {}).get("x"), 0.5)
    ay = safe_float((style.get("anchor") or {}).get("y"), 0.6875)
    mode = str(position_mode or "reset").strip().lower()
    if mode in {"reset", "center"}:
        return 0.0, 0.0, "reset"
    if mode == "none":
        return 0.0, 0.0, "none"
    if mode == "detected_fcpx":
        return (ax - 0.5) * width, (0.5 - ay) * height, "detected_fcpx"
    if mode == "detected_resolve":
        return (ax - 0.5) * width, (ay - 0.5) * height, "detected_resolve"
    if mode == "custom":
        return float(position_x), float(position_y), "custom"
    return 0.0, 0.0, "reset"


def position_to_fcpxml_units(x: float, y: float, mode: str, height: int) -> Tuple[float, float]:
    # Resolve's FCPXML importer scales position by frame_height / 100.
    # Detected positions from compute_position are target Resolve pixels.
    if mode in {"detected_fcpx", "detected_resolve"}:
        scale = 100.0 / max(1, height)
        return x * scale, y * scale
    return x, y


def build_title_xml(
    cue: Dict[str, Any],
    style: Dict[str, Any],
    fps: float,
    width: int,
    height: int,
    effect_ref: str,
    lane: int,
    title_prefix: str,
    position_mode: str = "reset",
    position_x: float = 0.0,
    position_y: float = 0.0,
    indent: str = "        ",
) -> str:
    idx = safe_int(cue.get("index"), 1)
    lane = max(1, safe_int(cue.get("lane"), lane))
    start_frames = safe_int(cue.get("start_frame"), sec_to_frames(safe_float(cue.get("start"), 0.0), fps))
    duration_frames = max(1, safe_int(cue.get("duration_frames"), sec_to_frames(safe_float(cue.get("duration"), 1.0 / fps), fps)))
    offset = frames_to_fcpx_time(start_frames, fps)
    duration = frames_to_fcpx_time(duration_frames, fps)
    text = xml_escape(cue.get("text") or "")
    title_name = xml_escape(f"{title_prefix} {idx:04d} - {cue.get('text', '')}"[:120])
    text_style_id = f"ts{idx}"

    cue_position_mode = str(cue.get("position_mode") or "").strip().lower()
    effective_position_mode = "detected_fcpx" if cue_position_mode == "detected_fcpx" else position_mode
    pos_x, pos_y, mode = compute_position(style, width, height, effective_position_mode, position_x, position_y)
    pos_x, pos_y = position_to_fcpxml_units(pos_x, pos_y, mode, height)
    if mode == "none":
        transform_line = ""
    else:
        rotation = safe_float(style.get("static_rotation_degrees"), 0.0)
        rotation_attr = f' rotation="{rotation:.3f}"' if rotation else ""
        transform_line = f'{indent}  <adjust-transform position="{pos_x:.3f} {pos_y:.3f}" anchor="0 0" scale="1 1"{rotation_attr}/>\n'

    style_attrs = fcpxml_text_style_attrs(style)

    return f'''{indent}<title ref="{effect_ref}" name="{title_name}" lane="{lane}" offset="{offset}" start="0s" duration="{duration}">
{transform_line}{indent}  <text>
{indent}    <text-style ref="{text_style_id}">{text}</text-style>
{indent}  </text>
{indent}  <text-style-def id="{text_style_id}">
{indent}    <text-style {style_attrs}/>
{indent}  </text-style-def>
{indent}</title>'''



def _native_title_advance(text: str, font: str, units: int, bold: bool) -> float:
    """Measure the installed font, not OCR word-length or a guessed glyph width."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Size(ctypes.Structure):
            _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

        gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        user = ctypes.WinDLL("user32", use_last_error=True)
        gdi.CreateFontW.restype = wintypes.HANDLE
        gdi.CreateFontW.argtypes = [ctypes.c_int] * 13 + [wintypes.LPCWSTR]
        gdi.SelectObject.restype = wintypes.HANDLE
        gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
        gdi.GetTextExtentPoint32W.restype = wintypes.BOOL
        gdi.GetTextExtentPoint32W.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(Size)]
        gdi.DeleteObject.argtypes = [wintypes.HANDLE]
        user.GetDC.restype = wintypes.HDC
        user.GetDC.argtypes = [wintypes.HWND]
        user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        dc = user.GetDC(None)
        if not dc:
            raise RuntimeError("Cannot measure Resolve title font: Windows DC unavailable")
        handle = gdi.CreateFontW(-units, 0, 0, 0, 700 if bold else 400, 0, 0, 0, 1, 0, 0, 0, 0, font)
        if not handle:
            user.ReleaseDC(None, dc)
            raise RuntimeError(f"Cannot measure Resolve title font: {font}")
        previous = gdi.SelectObject(dc, handle)
        size = Size()
        try:
            if not previous or not gdi.GetTextExtentPoint32W(dc, text, len(text), ctypes.byref(size)):
                raise RuntimeError(f"Cannot measure Resolve title glyphs: {font}")
            return float(size.cx)
        finally:
            gdi.SelectObject(dc, previous)
            gdi.DeleteObject(handle)
            user.ReleaseDC(None, dc)
    # Offline non-Windows replay; production uses the installed Windows font.
    try:
        from PIL import ImageFont
    except ImportError as error:
        raise RuntimeError("Font measurement unavailable; cannot publish unbounded titles") from error
    font_path = "LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf"
    try:
        face = ImageFont.truetype(font_path, units)
    except OSError as error:
        raise RuntimeError("Offline Arial-compatible font unavailable for geometry check") from error
    return float(face.getlength(text))


def _layout_caption_titles(
    cues: List[Dict[str, Any]], base_style: Dict[str, Any], cue_styles: Optional[Dict[int, Dict[str, Any]]],
    width: int, height: int, position_mode: str,
) -> Tuple[List[Dict[str, Any]], Dict[int, Dict[str, Any]]]:
    """Constrain rendered Basic Titles in space AND time, preserving every cue interval.

    OCR/source geometry stays authoritative for the initial placement. The output
    adapter may minimally scale or shift individual glyph boxes when they collide.
    No source IDs, caption text, timing, lanes, detection or animation DNA change.
    """
    padding = max(8.0, width * 0.012)
    title_styles = {int(c['index']): dict(style_for_cue(c, base_style, cue_styles)) for c in cues}
    # Preserve OCR boxes only for confirmed multiword phrase-state compositions.
    # Other source-backed words retain the established collision layout (Reel #4).
    phrase_compositions = {
        str(c['visual_composition_id'])
        for c in cues
        if c.get('source_observed_phrase_state')
        and c.get('visual_composition_id')
        and len(str(c.get('text') or '').split()) >= 2
    }
    placed: List[Tuple[int, int, float, float, float, float, bool]] = []
    adjusted = []
    # Earlier appearing titles retain priority; source-backed visual titles win
    # over transcript fallbacks at identical starts.
    ordered = sorted(cues, key=lambda c: (
        safe_int(c.get('start_frame'), 0),
        1 if c.get('timing_authority') == 'transcript_fallback' else 0,
        safe_int(c.get('index'), 0),
    ))
    for cue in ordered:
        idx = int(cue['index'])
        original = title_styles[idx]
        mode = 'detected_fcpx' if cue.get('position_mode') == 'detected_fcpx' else position_mode
        if mode not in {'reset', 'center', 'detected_fcpx', 'detected_resolve'}:
            raise ValueError(f"Caption geometry requires a supported position mode: {mode}")
        anchor = original.get('anchor') or {}
        original_x = float(anchor.get('x', .5)) * width if mode.startswith('detected') else width / 2
        original_y = float(anchor.get('y', .5)) * height if mode.startswith('detected') else height / 2
        x0, y0 = original_x, original_y
        # OCR placement may be left/right aligned, while Resolve Basic Title
        # adjust-transform always positions its *center*. Use the observed box
        # center, not an OCR paragraph edge, for the renderer's transform.
        bbox = (original.get('placement') or {}).get('normalized_bbox')
        if (mode.startswith('detected') and isinstance(bbox, (list, tuple)) and len(bbox) == 4
                and all(isinstance(v, (int, float)) and math.isfinite(v) for v in bbox)
                and 0 <= bbox[0] < bbox[2] <= 1 and 0 <= bbox[1] < bbox[3] <= 1):
            x0 = (bbox[0] + bbox[2]) * width / 2
            y0 = (bbox[1] + bbox[3]) * height / 2
            # Sub-pixel OCR center variation is not an instruction to move
            # previously-good titles; only correct meaningful anchor errors.
            if abs(x0 - original_x) < 3.0:
                x0 = original_x
            if abs(y0 - original_y) < 3.0:
                y0 = original_y
        # Accepted OCR geometry is source authority, not a suggestion to move
        # independently observed titles when the selected font has new metrics.
        source_box = (
            cue.get('timing_authority') == 'visual_primary'
            and bool(cue.get('style_evidence_id'))
            and (bool(cue.get('source_observed_phrase_state'))
                 or bool(cue.get('visual_composition_id') in phrase_compositions))
            and mode.startswith('detected')
            and isinstance(bbox, (list, tuple)) and len(bbox) == 4
            and all(isinstance(v, (int, float)) and math.isfinite(v) for v in bbox)
            and 0 <= bbox[0] < bbox[2] <= 1 and 0 <= bbox[1] < bbox[3] <= 1
        )
        font_px = float(original['font_size_px'])
        if not math.isfinite(font_px) or font_px <= 0:
            raise ValueError(f"Caption {idx}: invalid font height")
        text = str(cue.get('text') or '').strip()
        lines = text.splitlines() or ['']
        units = max(1, round(font_px / RESOLVE21_BASIC_TITLE_RENDER_PX_PER_FCPXML_FONT_UNIT))
        advance = max(_native_title_advance(line, str(original['font_name']), units, bool(original.get('bold'))) for line in lines)
        stroke = max(0.0, float(original.get('outline_px') or 0))
        # Same native-renderer advance calibration as fontSize; add outline and
        # modest glyph overhang so the measured rectangles are conservative.
        glyph_width = advance * RESOLVE21_BASIC_TITLE_RENDER_PX_PER_FCPXML_FONT_UNIT * 1.04
        glyph_height = font_px * 1.10 * len(lines)
        if source_box:
            # A different installed font can be wider than the source glyphs.
            # Fit within the directly observed source box; do not relocate the
            # title into an unrelated visual composition or across baked text.
            allowed_w = (bbox[2] - bbox[0]) * width * 1.12
            allowed_h = (bbox[3] - bbox[1]) * height * 1.12
            scale = min(1., max(0.01, (allowed_w - 2 * stroke) / max(1., glyph_width)),
                        max(0.01, (allowed_h - 2 * stroke) / max(1., glyph_height)))
            if scale < 0.999 or abs(x0 - original_x) > 0.001 or abs(y0 - original_y) > 0.001:
                st = dict(original)
                st['font_size_px'] = max(1, round(font_px * scale))
                st['anchor'] = {'x': x0 / width, 'y': y0 / height}
                title_styles[idx] = st
                changed = dict(cue)
                changed['position_mode'] = 'detected_fcpx'
                adjusted.append(changed)
            else:
                adjusted.append(cue)
            # Keep source-anchored titles as obstacles for transcript-only
            # fallbacks, but never move another directly observed source title.
            start = safe_int(cue.get('start_frame'), 0)
            end = start + max(1, safe_int(cue.get('duration_frames'), 1))
            placed.append((start, end, x0, y0,
                           glyph_width * scale + 2 * stroke + 4,
                           glyph_height * scale + 2 * stroke + 4, True))
            continue
        start = safe_int(cue.get('start_frame'), 0)
        end = start + max(1, safe_int(cue.get('duration_frames'), 1))
        active = [other for other in placed if start < other[1] and other[0] < end
                  and not (other[6] and cue.get('timing_authority') == 'visual_primary'
                           and cue.get('visual_event_identity'))]
        # Preserve original positions if they are safe; select the smallest
        # per-title correction otherwise. Never relocate an unrelated title.
        solutions = []
        for scale in (1., .96, .92, .87, .82, .76, .70, .63, .55, .46, .38):
            w, h = glyph_width * scale + 2 * stroke + 4, glyph_height * scale + 2 * stroke + 4
            if w > width - 2 * padding or h > height - 2 * padding:
                continue
            safe_x = min(max(x0, padding + w/2), width - padding - w/2)
            safe_y = min(max(y0, padding + h/2), height - padding - h/2)
            for dy in (0, -16, 16, -32, 32, -48, 48, -72, 72, -96, 96, -128, 128, -160, 160):
                y = safe_y + dy
                if y - h/2 < padding or y + h/2 > height-padding:
                    continue
                for dx in (0, -24, 24, -48, 48, -80, 80):
                    x = safe_x + dx
                    if x - w/2 < padding or x + w/2 > width-padding:
                        continue
                    if any(abs(x-px) < (w+pw)/2 + padding and abs(y-py) < (h+ph)/2 + padding
                   for _,_,px,py,pw,ph,_ in active):
                        continue
                    cost = (abs(x-x0) * 1.15 + abs(y-y0)
                            + (1-scale) * 330 + (0 if dx==0 else 0.05))
                    solutions.append((round(cost, 4), -scale, abs(dy), abs(dx), x, y, scale, w, h))
            if solutions and scale <= .70:
                break
        fallback = not solutions
        if fallback:
            # Search the edges of occupied boxes when nearby offsets are exhausted.
            for scale in (1., .92, .82, .70, .55, .46, .38):
                w, h = glyph_width * scale + 2 * stroke + 4, glyph_height * scale + 2 * stroke + 4
                if w > width - 2 * padding or h > height - 2 * padding:
                    continue
                xs = [x0, padding + w/2, width - padding - w/2]
                ys = [y0, padding + h/2, height - padding - h/2]
                for _, _, px, py, pw, ph, _ in active:
                    xs.extend((px - (w+pw)/2 - padding, px + (w+pw)/2 + padding))
                    ys.extend((py - (h+ph)/2 - padding, py + (h+ph)/2 + padding))
                for y in ys:
                    if y - h/2 < padding or y + h/2 > height-padding:
                        continue
                    for x in xs:
                        if x - w/2 < padding or x + w/2 > width-padding:
                            continue
                        if any(abs(x-px) < (w+pw)/2 + padding and abs(y-py) < (h+ph)/2 + padding
                               for _,_,px,py,pw,ph,_ in active):
                            continue
                        cost = abs(x-x0) * 1.15 + abs(y-y0) + (1-scale) * 330
                        solutions.append((round(cost, 4), -scale, abs(y-y0), abs(x-x0), x, y, scale, w, h))
        if not solutions:
            raise ValueError(f"Caption layout has no non-overlapping visible placement at frame {start}: title {idx} ({text!r})")
        _, _, _, _, x, y, scale, w, h = min(solutions)
        if abs(x-original_x) > 0.001 or abs(y-original_y) > 0.001 or scale < .999:
            st = dict(original)
            st['font_size_px'] = max(1, round(font_px * scale))
            st['anchor'] = {'x': x/width, 'y': y/height}
            title_styles[idx] = st
            changed = dict(cue)
            changed['position_mode'] = 'detected_fcpx'
            if fallback:
                changed['layout_fallback'] = {'reason': 'nearby_positions_occupied', 'scale': scale,
                                              'shift_px': [round(x-x0, 2), round(y-y0, 2)]}
            adjusted.append(changed)
        else:
            adjusted.append(cue)
        placed.append((start,end,x,y,w,h,bool(cue.get('source_observed_phrase_state'))))
    by_id = {int(c['index']): c for c in adjusted}
    return [by_id[int(c['index'])] for c in cues], title_styles

def build_caption_only_fcpxml(
    cues: List[Dict[str, Any]],
    style: Dict[str, Any],
    cue_styles: Optional[Dict[int, Dict[str, Any]]],
    fps: float,
    width: int,
    height: int,
    timeline_name: str,
    title_prefix: str,
    fcpxml_version: str,
    effect_uid: str,
    lane: int,
    position_mode: str,
    position_x: float,
    position_y: float,
) -> str:
    total_frames = max([safe_int(c.get("end_frame"), 0) for c in cues] or [1])
    total_duration = frames_to_fcpx_time(max(1, total_frames), fps)
    format_id = "r1"
    effect_id = "r2"
    timeline_name_xml = xml_escape(timeline_name)
    format_name = f"FFVideoFormat{width}x{height}p{int(round(fps))}"
    laid_out, layout_styles = _layout_caption_titles(cues, style, cue_styles, width, height, position_mode)
    title_xml = "\n".join(build_title_xml(c, layout_styles[int(c["index"])], fps, width, height, effect_id, lane, title_prefix, position_mode, position_x, position_y) for c in laid_out)

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="{xml_escape(fcpxml_version)}">
  <resources>
    <format id="{format_id}" name="{xml_escape(format_name)}" frameDuration="1/{int(round(fps))}s" width="{width}" height="{height}" colorSpace="1-1-1 (Rec. 709)"/>
    <effect id="{effect_id}" name="Basic Title" uid="{xml_escape(effect_uid)}"/>
  </resources>
  <library>
    <event name="Video Cloner">
      <project name="{timeline_name_xml}">
        <sequence format="{format_id}" duration="{total_duration}" tcStart="0s" tcFormat="NDF">
          <spine>
            <gap name="Video Cloner Caption Layer" offset="0s" start="0s" duration="{total_duration}">
{title_xml}
            </gap>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
'''


def build_video_primary_xml(video_clips: List[Dict[str, Any]], video_ref: str, fps: float, transitions: Optional[List[Dict[str, Any]]] = None, transition_resource_ids: Optional[Dict[str, str]] = None, transition_mode: str = "native") -> str:
    lines: List[str] = []
    current_frame = 0
    transition_resource_ids = transition_resource_ids or {}
    transition_mode_l = str(transition_mode or "none").lower()
    transitions_by_boundary: Dict[int, Dict[str, Any]] = {}
    if transition_mode_l in {"native", "hybrid"}:
        for transition in transitions or []:
            if str(transition.get("backend") or "native") != "native":
                continue
            boundary = safe_int(transition.get("boundary_frame"), -1)
            if boundary >= 0:
                transitions_by_boundary[boundary] = transition

    for clip in sorted(video_clips, key=lambda c: safe_int(c.get("timeline_start_frame"), 0)):
        start_frame = safe_int(clip.get("timeline_start_frame"), 0)
        dur_frame = max(1, safe_int(clip.get("timeline_duration_frames"), 1))
        source_start_frame = max(0, safe_int(clip.get("source_start_frame"), 0))
        if start_frame > current_frame:
            gap_dur = start_frame - current_frame
            lines.append(f'        <gap name="VC Gap" offset="{frames_to_fcpx_time(current_frame, fps)}" start="0s" duration="{frames_to_fcpx_time(gap_dur, fps)}"/>')
            current_frame = start_frame
        # If the chosen clips overlap due bad source data, clamp to current.
        if start_frame < current_frame:
            start_frame = current_frame
        name = xml_escape(clip.get("name") or f"VC_OP_{clip.get('index', 1):03d}_cut")
        lines.append(
            f'        <asset-clip name="{name}" ref="{video_ref}" offset="{frames_to_fcpx_time(start_frame, fps)}" '
            f'start="{frames_to_fcpx_time(source_start_frame, fps)}" duration="{frames_to_fcpx_time(dur_frame, fps)}"/>'
        )
        current_frame = max(current_frame, start_frame + dur_frame)

        transition = transitions_by_boundary.get(current_frame)
        if transition:
            effect_key = str(transition.get("effect_key") or "cross_dissolve")
            effect_ref = transition_resource_ids.get(effect_key)
            if effect_ref:
                lines.append(build_transition_xml(transition, effect_ref=effect_ref, fps=fps, indent="        "))

    return "\n".join(lines)

def build_full_timeline_fcpxml(
    cues: List[Dict[str, Any]],
    video_clips: List[Dict[str, Any]],
    style: Dict[str, Any],
    cue_styles: Optional[Dict[int, Dict[str, Any]]],
    fps: float,
    width: int,
    height: int,
    timeline_name: str,
    title_prefix: str,
    fcpxml_version: str,
    effect_uid: str,
    title_lane: int,
    position_mode: str,
    position_x: float,
    position_y: float,
    video_path: str,
    audio_path: str,
    include_audio: bool,
    transitions: Optional[List[Dict[str, Any]]] = None,
    transition_mode: str = "hybrid",
    vfx_placeholder_lane: int = 2,
    vfx_placeholder_visible: bool = False,
    vfx_placeholder_prefix: str = "VC VFX Transition",
    layout_fallbacks: Optional[List[Dict[str, Any]]] = None,
) -> str:
    max_cue_frame = max([safe_int(c.get("end_frame"), 0) for c in cues] or [1])
    max_video_frame = max([safe_int(c.get("timeline_end_frame"), 0) for c in video_clips] or [1])
    total_frames = max(1, max_cue_frame, max_video_frame)
    total_duration = frames_to_fcpx_time(total_frames, fps)

    format_id = "r1"
    effect_id = "r2"
    video_asset_id = "r3"
    audio_asset_id = "r4"
    transition_resources_xml, transition_resource_ids = build_transition_resources(transitions or [], start_index=5)
    transition_resources_block = ("\n" + transition_resources_xml) if transition_resources_xml else ""
    timeline_name_xml = xml_escape(timeline_name)
    format_name = f"FFVideoFormat{width}x{height}p{int(round(fps))}"

    video_name = xml_escape(Path(str(video_path)).name or "Video Cloner Source Video")
    video_url = xml_escape(path_to_file_url(video_path))
    audio_resource = ""
    if include_audio and audio_path:
        audio_name = xml_escape(Path(str(audio_path)).name or "Video Cloner Audio")
        audio_url = xml_escape(path_to_file_url(audio_path))
        audio_resource = f'\n    <asset id="{audio_asset_id}" name="{audio_name}" uid="{xml_escape(audio_path)}" src="{audio_url}" start="0s" duration="{total_duration}" hasAudio="1" audioSources="1" audioChannels="2" audioRate="48000"/>'

    primary_video_xml = build_video_primary_xml(video_clips, video_asset_id, fps, transitions=transitions or [], transition_resource_ids=transition_resource_ids, transition_mode=transition_mode)
    audio_xml = ""
    if include_audio and audio_path:
        # Connected audio lane below the primary video storyline.
        audio_xml = f'\n        <asset-clip name="VC Source Audio" ref="{audio_asset_id}" lane="-1" offset="0s" start="0s" duration="{total_duration}"/>'

    laid_out, layout_styles = _layout_caption_titles(cues, style, cue_styles, width, height, position_mode)
    if layout_fallbacks is not None:
        layout_fallbacks.extend({'id': c['id'], 'start_frame': c['start_frame'], **c['layout_fallback']}
                                for c in laid_out if c.get('layout_fallback'))
    title_xml = "\n".join(build_title_xml(c, layout_styles[int(c["index"])], fps, width, height, effect_id, title_lane, title_prefix, position_mode, position_x, position_y) for c in laid_out)
    vfx_placeholder_xml = build_vfx_placeholders_xml(
        transitions or [],
        effect_ref=effect_id,
        fps=fps,
        lane=max(1, int(vfx_placeholder_lane)),
        visible=bool(vfx_placeholder_visible),
        prefix=vfx_placeholder_prefix,
    )
    vfx_placeholder_block = ("\n" + vfx_placeholder_xml) if vfx_placeholder_xml else ""

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="{xml_escape(fcpxml_version)}">
  <resources>
    <format id="{format_id}" name="{xml_escape(format_name)}" frameDuration="1/{int(round(fps))}s" width="{width}" height="{height}" colorSpace="1-1-1 (Rec. 709)"/>
    <effect id="{effect_id}" name="Basic Title" uid="{xml_escape(effect_uid)}"/>
    <asset id="{video_asset_id}" name="{video_name}" uid="{xml_escape(video_path)}" src="{video_url}" start="0s" duration="{total_duration}" hasVideo="1" format="{format_id}"/>{audio_resource}{transition_resources_block}
  </resources>
  <library>
    <event name="Video Cloner">
      <project name="{timeline_name_xml}">
        <sequence format="{format_id}" duration="{total_duration}" tcStart="0s" tcFormat="NDF">
          <spine>
{primary_video_xml}{audio_xml}
{title_xml}{vfx_placeholder_block}
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
'''


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Compile styled Resolve/FCPXML editable title captions from Video Cloner generic commands.")
    p.add_argument("--generic", required=True, help="Path to *_generic_edit_commands.json")
    p.add_argument("--caption-style", required=True, help="Path to *_caption_style.json")
    p.add_argument("--caption-lifecycle-plan", default=None, help="Optional calibrated Step 3D lifecycle authority plan. Applies visual lifecycle windows and deterministic overlap lanes while preserving transcript text semantics.")
    p.add_argument("--output-fcpxml", required=True, help="Output .fcpxml path")
    p.add_argument("--report", required=True, help="Output report JSON path")
    p.add_argument("--source", default="auto", choices=["auto", "subtitle_clips", "commands"], help="Subtitle cue source inside generic JSON")
    p.add_argument("--profile-id", default="primary", help="caption_style profile id or 'primary'")
    p.add_argument("--use-style-events", type=str2bool, default=True, help="Use per-cue caption_style_events/style_events from detect_caption_style.py v5.2+ when available.")
    p.add_argument("--style-event-match-window-sec", type=float, default=1.25, help="Max timing distance used when matching subtitle cues to detected style events.")
    p.add_argument("--style-event-min-match-score", type=float, default=0.12, help="Minimum timing/text score required before a cue uses an event-specific style.")
    p.add_argument("--timeline-name", default=None, help="FCPXML project/timeline name")
    p.add_argument("--timeline-mode", default="caption_only", choices=["caption_only", "full_timeline"], help="caption_only = titles only. full_timeline = V1 video cuts + A1 audio + V2 title captions.")
    p.add_argument("--video", default=None, help="Video/proxy path for full_timeline mode. Recommended: proxyPath from Get Media Path.")
    p.add_argument("--audio", default=None, help="Optional WAV path for full_timeline mode. Recommended: audioPath from Get Media Path.")
    p.add_argument("--include-audio", type=str2bool, default=True, help="Include A1 audio asset in full_timeline mode if --audio exists.")
    p.add_argument("--include-transitions", type=str2bool, default=True, help="Write transition_hint operations into full_timeline FCPXML as native transitions when possible.")
    p.add_argument("--transition-mode", default="hybrid", choices=["native", "hybrid", "vfx_placeholders", "none"], help="hybrid = native simple transitions + invisible VFX placeholders for advanced effects. native = force all hints to native FCPXML transitions. vfx_placeholders = force all hints to upper-lane VFX placeholders. none = disable transitions.")
    p.add_argument("--vfx-placeholder-lane", type=int, default=2, help="Upper video lane for invisible VFX transition placeholder title clips. Use 2 when captions are on lane 1.")
    p.add_argument("--vfx-placeholder-visible", type=str2bool, default=False, help="If true, render visible yellow VFX labels for debugging. Default false keeps placeholders invisible.")
    p.add_argument("--vfx-placeholder-prefix", default="VC VFX Transition", help="Marker/value prefix for VFX placeholder clips.")
    p.add_argument("--transition-min-confidence", default="high", choices=["any", "low", "medium", "high", "very_high"], help="Minimum transition confidence to emit.")
    p.add_argument("--transition-default-duration-frames", type=int, default=8, help="Default transition duration when generic JSON does not provide one.")
    p.add_argument("--transition-max-duration-frames", type=int, default=24, help="Clamp native transition duration to this many frames.")
    p.add_argument("--transition-boundary-tolerance-frames", type=int, default=6, help="Allowed distance from transition_hint cut_frame to the nearest video clip edit point.")
    p.add_argument("--require-transition-handles", type=str2bool, default=True, help="Skip transitions when analysis says required handles are missing.")
    p.add_argument("--transition-effect-fallback", default="mapped", choices=["mapped", "cross_dissolve"], help="mapped = slide/wipe/fade mappings. cross_dissolve = safest placeholder for all hints.")
    p.add_argument("--fps", type=float, default=0.0, help="Override FPS. 0 = auto from generic or 24")
    p.add_argument("--width", type=int, default=1080)
    p.add_argument("--height", type=int, default=1920)
    p.add_argument("--fcpxml-version", default="1.10")
    p.add_argument("--effect-uid", default=DEFAULT_BASIC_TITLE_UID)
    p.add_argument("--title-prefix", default="VC Caption")
    p.add_argument("--lane", type=int, default=1, help="FCPXML title lane. Use 1 to place titles above the primary video storyline.")
    p.add_argument("--position-mode", default="reset", choices=["reset", "none", "center", "detected_fcpx", "detected_resolve", "custom"], help="How to write title clip transform. 'reset' keeps Resolve Position X/Y at 0/0 and is the visible-safe default.")
    p.add_argument("--position-x", type=float, default=0.0, help="Custom transform X when --position-mode custom")
    p.add_argument("--position-y", type=float, default=0.0, help="Custom transform Y when --position-mode custom")
    p.add_argument("--font-name", default=None, help="Override detected font family")
    p.add_argument("--font-size", type=int, default=0, help="Override detected font size px")
    p.add_argument("--font-scale", type=float, default=1.0)
    p.add_argument("--outline-scale", type=float, default=1.0)
    p.add_argument("--shadow-scale", type=float, default=1.0)
    p.add_argument("--fill", default=None, help="Override fill hex, e.g. #ffffff")
    p.add_argument("--outline", default=None, help="Override outline/stroke hex")
    p.add_argument("--shadow", default=None, help="Override shadow hex")
    p.add_argument("--min-duration-frames", type=int, default=1)
    p.add_argument("--prevent-overlap", type=str2bool, default=True)
    p.add_argument("--max-cues", type=int, default=0)
    p.add_argument("--encoding", default="utf-8", choices=["utf-8", "utf-8-sig"])
    return p


def main(argv: Optional[List[str]] = None) -> int:
    started = now_unix()
    args = build_arg_parser().parse_args(argv)

    report: Dict[str, Any] = {
        "success": False,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "started_at_unix": started,
        "inputs": {
            "generic": args.generic,
            "caption_style": args.caption_style,
            "caption_lifecycle_plan": args.caption_lifecycle_plan,
            "source": args.source,
            "profile_id": args.profile_id,
            "timeline_mode": args.timeline_mode,
            "use_style_events": args.use_style_events,
            "style_event_match_window_sec": args.style_event_match_window_sec,
            "style_event_min_match_score": args.style_event_min_match_score,
            "video": args.video,
            "audio": args.audio,
            "include_transitions": args.include_transitions,
            "transition_mode": args.transition_mode,
            "transition_min_confidence": args.transition_min_confidence,
            "vfx_placeholder_lane": getattr(args, "vfx_placeholder_lane", 2),
            "vfx_placeholder_visible": getattr(args, "vfx_placeholder_visible", False),
        },
        "outputs": {
            "fcpxml": args.output_fcpxml,
            "report": args.report,
        },
        "errors": [],
        "warnings": [],
    }

    try:
        generic = load_json(args.generic)
        caption_style = load_json(args.caption_style)

        fps = safe_float(args.fps, 0.0) if args.fps else 0.0
        if fps <= 0:
            fps = extract_fps(generic, fallback=24.0)
        if fps <= 0:
            fps = 24.0

        overrides = {
            "font_name": args.font_name,
            "font_size": args.font_size if args.font_size and args.font_size > 0 else None,
            "font_scale": args.font_scale,
            "outline_scale": args.outline_scale,
            "shadow_scale": args.shadow_scale,
            "fill": args.fill,
            "outline": args.outline,
            "shadow": args.shadow,
        }
        style = extract_style_contract(caption_style, profile_id=args.profile_id, overrides=overrides)

        raw_cues, source_info = extract_subtitle_cues(generic, source=args.source, fps=fps)
        cues = enforce_timing_rules(
            raw_cues,
            fps=fps,
            min_duration_frames=max(1, args.min_duration_frames),
            prevent_overlap=bool(args.prevent_overlap),
            max_cues=max(0, args.max_cues),
        )
        if not cues:
            raise RuntimeError("No subtitle cues were found in generic edit commands. Expected subtitle_clips/captions/subtitles or text commands.")

        cue_styles, style_event_info = assign_style_events_to_cues(
            cues=cues,
            style_data=caption_style,
            base_style=style,
            overrides=overrides,
            fps=fps,
            enabled=bool(args.use_style_events),
            match_window_sec=max(0.05, safe_float(args.style_event_match_window_sec, 1.25)),
            min_match_score=max(0.0, safe_float(args.style_event_min_match_score, 0.12)),
        )

        lifecycle_info: Dict[str, Any] = {"enabled": False}
        if args.caption_lifecycle_plan:
            lifecycle_plan = load_json(args.caption_lifecycle_plan)
            cues, lifecycle_info = apply_caption_lifecycle_plan(
                cues=cues,
                plan=lifecycle_plan,
                fps=fps,
                base_lane=max(1, args.lane),
            )
            report["warnings"].append(
                "Calibrated caption lifecycle windows override transcript timing and preserve overlaps using deterministic FCPXML lanes."
            )

        cue_total_duration = max((safe_float(c.get("end"), 0.0) for c in cues), default=0.0)
        video_path = args.video or find_first_scalar(generic, ["source_video", "video_path", "proxy_path", "sourceVideo", "source_video_path"])
        audio_path = args.audio or find_first_scalar(generic, ["source_audio", "audio_path", "wav_path", "sourceAudio", "source_audio_path"])

        video_clips: List[Dict[str, Any]] = []
        video_info: Dict[str, Any] = {}
        transitions: List[Dict[str, Any]] = []
        transition_info: Dict[str, Any] = {"include_transitions": bool(args.include_transitions), "transition_mode": args.transition_mode}
        if args.timeline_mode == "full_timeline":
            if not video_path:
                report["warnings"].append("--timeline-mode full_timeline requested, but no --video path was provided and no source video path was found in generic JSON. The FCPXML will still be written as caption_only fallback.")
                args.timeline_mode = "caption_only"
            else:
                video_clips, video_info = extract_video_clips(generic, fps=fps, total_duration_hint=cue_total_duration)
                if video_info.get("fallback_continuous_clip"):
                    report["warnings"].append("No reliable video cut list was found in generic JSON. full_timeline uses one continuous fallback video clip. If you need exact OTIO cuts, make sure generic_edit_commands includes clip list with source_start/source_end/timeline_start/timeline_end.")

                transitions, transition_info = extract_transition_hints(
                    generic=generic,
                    fps=fps,
                    video_clips=video_clips,
                    include_transitions=bool(args.include_transitions),
                    transition_mode=args.transition_mode,
                    min_confidence=args.transition_min_confidence,
                    default_duration_frames=max(1, args.transition_default_duration_frames),
                    max_duration_frames=max(1, args.transition_max_duration_frames),
                    boundary_tolerance_frames=max(0, args.transition_boundary_tolerance_frames),
                    require_handles=bool(args.require_transition_handles),
                    effect_fallback_mode=args.transition_effect_fallback,
                )
                if args.include_transitions and args.transition_mode != "none" and not transitions:
                    report["warnings"].append("No FCPXML transitions were written. Either no transition_hint operations matched video edit boundaries, confidence was below threshold, or handles were missing.")

        timeline_base = Path(args.generic).stem.replace("_generic_edit_commands", "")
        default_suffix = "_textplus_full" if args.timeline_mode == "full_timeline" else "_textplus_captions"
        timeline_name = args.timeline_name or f"{timeline_base}{default_suffix}"
        effective_vfx_placeholder_lane = max(1, args.vfx_placeholder_lane)
        if lifecycle_info.get("enabled") and args.transition_mode in {"hybrid", "vfx_placeholders"}:
            max_caption_lane = safe_int((lifecycle_info.get("lane_allocation") or {}).get("max_lane"), max(1, args.lane))
            if effective_vfx_placeholder_lane <= max_caption_lane:
                effective_vfx_placeholder_lane = max_caption_lane + 1
                report["warnings"].append(
                    f"VFX placeholder lane moved to {effective_vfx_placeholder_lane} to avoid calibrated caption lanes."
                )

        if args.timeline_mode == "full_timeline":
            fcpxml_text = build_full_timeline_fcpxml(
                cues=cues,
                video_clips=video_clips,
                style=style,
                cue_styles=cue_styles,
                fps=fps,
                width=max(1, args.width),
                height=max(1, args.height),
                timeline_name=timeline_name,
                title_prefix=args.title_prefix,
                fcpxml_version=args.fcpxml_version,
                effect_uid=args.effect_uid,
                title_lane=max(1, args.lane),
                position_mode=args.position_mode,
                position_x=args.position_x,
                position_y=args.position_y,
                video_path=str(video_path),
                audio_path=str(audio_path or ""),
                include_audio=bool(args.include_audio and audio_path),
                transitions=transitions,
                transition_mode=args.transition_mode,
                vfx_placeholder_lane=effective_vfx_placeholder_lane,
                vfx_placeholder_visible=bool(args.vfx_placeholder_visible),
                vfx_placeholder_prefix=args.vfx_placeholder_prefix,
            )
        else:
            fcpxml_text = build_caption_only_fcpxml(
                cues=cues,
                style=style,
                cue_styles=cue_styles,
                fps=fps,
                width=max(1, args.width),
                height=max(1, args.height),
                timeline_name=timeline_name,
                title_prefix=args.title_prefix,
                fcpxml_version=args.fcpxml_version,
                effect_uid=args.effect_uid,
                lane=max(1, args.lane),
                position_mode=args.position_mode,
                position_x=args.position_x,
                position_y=args.position_y,
            )

        out_path = Path(args.output_fcpxml)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(fcpxml_text, encoding=args.encoding)

        durations = [safe_float(c.get("duration"), 0.0) for c in cues]
        words_per = [len(norm_text(c.get("text")).split()) for c in cues]
        pos_x, pos_y, pos_mode_written = compute_position(style, max(1, args.width), max(1, args.height), args.position_mode, args.position_x, args.position_y)
        pos_x, pos_y = position_to_fcpxml_units(pos_x, pos_y, pos_mode_written, args.height)
        report.update({
            "success": True,
            "timing": {
                "fps": fps,
                "cue_count": len(cues),
                "raw_cue_count": len(raw_cues),
                "source": source_info,
                "min_duration_frames": args.min_duration_frames,
                "prevent_overlap": bool(args.prevent_overlap),
                "max_cues": args.max_cues,
                "word_level_likely": (sum(words_per) / max(1, len(words_per))) <= 1.25,
                "avg_words_per_cue": round(sum(words_per) / max(1, len(words_per)), 4),
                "first_cue": {k: cues[0].get(k) for k in ("index", "id", "text", "start", "end", "duration", "start_frame", "end_frame", "duration_frames")},
                "last_cue": {k: cues[-1].get(k) for k in ("index", "id", "text", "start", "end", "duration", "start_frame", "end_frame", "duration_frames")},
                "duration_min": round(min(durations), 6) if durations else None,
                "duration_max": round(max(durations), 6) if durations else None,
            },
            "style": {
                "style_contract": style,
                "per_cue_style_events": style_event_info,
                "position_fcpxml": {
                    "mode": args.position_mode,
                    "written_transform": {"x": round(pos_x, 3), "y": round(pos_y, 3), "mode": pos_mode_written},
                    "detected_fcpx": {
                        "x": round((style["anchor"]["x"] - 0.5) * max(1, args.width), 3),
                        "y": round((0.5 - style["anchor"]["y"]) * max(1, args.height), 3),
                    },
                    "detected_resolve": {
                        "x": round((style["anchor"]["x"] - 0.5) * max(1, args.width), 3),
                        "y": round((style["anchor"]["y"] - 0.5) * max(1, args.height), 3),
                    },
                    "visibility_fix": "Default --position-mode reset writes Resolve-safe Position X/Y = 0/0.",
                },
            },
            "caption_lifecycle": lifecycle_info,
            "video": {
                "timeline_mode": args.timeline_mode,
                "video_path": video_path,
                "audio_path": audio_path,
                "include_audio": bool(args.include_audio and audio_path),
                "video_clip_count": len(video_clips),
                "video_extraction": video_info,
                "first_video_clip": {k: video_clips[0].get(k) for k in ("index", "id", "name", "source_start", "timeline_start", "timeline_duration", "timeline_start_frame", "timeline_duration_frames")} if video_clips else None,
            },
            "transitions": {
                "enabled": bool(args.include_transitions and args.transition_mode != "none"),
                "mode": args.transition_mode,
                "total_count": len(transitions),
                "native_written": sum(1 for t in transitions if t.get("backend") == "native"),
                "vfx_placeholders_written": sum(1 for t in transitions if t.get("backend") == "vfx_placeholder"),
                "cut_only_count": sum(1 for t in transitions if t.get("backend") == "cut_only"),
                "info": transition_info,
                "first_transition": {k: transitions[0].get(k) for k in ("index", "transition_type", "backend", "confidence", "boundary_frame", "duration_frames", "effect_key", "effect_name")} if transitions else None,
                "vfx_placeholder_lane": effective_vfx_placeholder_lane,
                "vfx_placeholder_visible": bool(args.vfx_placeholder_visible),
                "note": "v1.4 hybrid mode writes simple transitions as native FCPXML <transition> elements and advanced viral transitions as invisible upper-lane VFX placeholder title clips for a later Resolve/Fusion applier.",
            },
            "fcpxml": {
                "version": args.fcpxml_version,
                "timeline_name": timeline_name,
                "width": args.width,
                "height": args.height,
                "effect_uid": args.effect_uid,
                "title_clips_written": len(cues),
                "encoding": args.encoding,
                "timeline_mode": args.timeline_mode,
                "caption_only_timeline": args.timeline_mode == "caption_only",
                "full_timeline": args.timeline_mode == "full_timeline",
                "position_mode": args.position_mode,
                "caption_lifecycle_plan_applied": bool(lifecycle_info.get("enabled")),
                "caption_lane_count": (lifecycle_info.get("lane_allocation") or {}).get("lane_count", 1),
                "caption_max_lane": (lifecycle_info.get("lane_allocation") or {}).get("max_lane", max(1, args.lane)),
            },
            "compatibility": {
                "primary_use": "Import FCPXML into Resolve. caption_only creates title-only timeline; full_timeline creates V1 video + A1 audio + V2 editable title captions.",
                "why_not_native_subtitles": "Resolve Free/external scripting path did not expose reliable automatic native subtitle styling.",
                "visibility_fix": "Default --position-mode reset writes Resolve-safe Position X/Y = 0/0. The previous detected transform hid titles.",
                "full_timeline_note": "full_timeline avoids manual copy/paste and avoids dragging nested caption timelines over the edited video.",
                "transition_note": "v1.6 keeps per-cue styles and hybrid transitions while optionally applying calibrated visual lifecycles on separate overlap-safe lanes.",
            },
            "runtime_sec": round(now_unix() - started, 4),
        })
        write_json(args.report, report)
        print(json.dumps({
            "success": True,
            "version": VERSION,
            "fcpxml": args.output_fcpxml,
            "report": args.report,
            "cue_count": len(cues),
            "style_profile": style.get("profile_id"),
            "style_event_matches": style_event_info.get("matched_cue_count", 0),
            "style_event_match_ratio": style_event_info.get("match_ratio", 0.0),
            "caption_lifecycle_plan_applied": bool(lifecycle_info.get("enabled")),
            "caption_lane_count": (lifecycle_info.get("lane_allocation") or {}).get("lane_count", 1),
            "position_mode": args.position_mode,
            "timeline_mode": args.timeline_mode,
            "video_clip_count": len(video_clips),
            "transition_count": len(transitions),
            "native_transition_count": sum(1 for t in transitions if t.get("backend") == "native"),
            "vfx_placeholder_count": sum(1 for t in transitions if t.get("backend") == "vfx_placeholder"),
            "warnings_count": len(report.get("warnings") or []),
            "errors_count": 0,
        }, ensure_ascii=False), flush=True)
        return 0

    except BaseException as exc:
        report["success"] = False
        report["errors"].append({"type": type(exc).__name__, "message": str(exc)})
        report["runtime_sec"] = round(now_unix() - started, 4)
        try:
            write_json(args.report, report)
        except Exception:
            pass
        print(json.dumps({
            "success": False,
            "version": VERSION,
            "report": args.report,
            "error": str(exc),
            "errors_count": len(report.get("errors") or []),
        }, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
