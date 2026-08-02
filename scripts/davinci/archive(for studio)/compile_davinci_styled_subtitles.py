#!/usr/bin/env python3
"""
compile_davinci_styled_subtitles.py

Video Cloner styled subtitle compiler for DaVinci Resolve workflows.

Purpose:
    generic_edit_commands.subtitle_clips
    + detect_caption_style.py caption_style_resolved / caption_style_profiles
    -> styled .ass subtitle file
    -> fallback .srt subtitle file
    -> style/report JSON for Resolve/manual/editor adapters

Important:
    SRT is the safest Resolve-native subtitle-track import path, but SRT carries almost no style.
    ASS carries font size, fill, outline, shadow, and exact position. Some editors preserve ASS
    styling, while Resolve subtitle-track import may not preserve all ASS styling depending on
    version/workflow. This script therefore produces both:
      - .ass = style-rich source of truth / preview / future adapters
      - .srt = Resolve-native timing fallback
      - .json = exact style contract for downstream Resolve/OpenReel/Text+ adapters
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

VERSION = "davinci_styled_subtitle_compiler_v1_ass_srt_style_contract"
SCHEMA = "video_cloner_davinci_styled_subtitles"
SCHEMA_VERSION = "1.0"


# -----------------------------
# Basic helpers
# -----------------------------


def str2bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    value = str(value).strip().lower()
    if value in ("yes", "true", "t", "1", "y", "on"):
        return True
    if value in ("no", "false", "f", "0", "n", "off"):
        return False
    raise argparse.ArgumentTypeError(f"Boolean value expected, got: {value}")


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, data: Dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return default
        return value
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


def clean_text(text: Any) -> str:
    text = str(text or "")
    text = text.replace("\u200b", "")
    return re.sub(r"\s+", " ", text).strip()


def word_count(text: Any) -> int:
    text = clean_text(text)
    if not text:
        return 0
    return len(re.findall(r"[\w'’]+", text, flags=re.UNICODE))


# -----------------------------
# Time helpers
# -----------------------------


def seconds_from_fields(obj: Dict[str, Any], fps: float) -> Tuple[Optional[float], Optional[float]]:
    """Extract start/end seconds from flexible generic subtitle clip shapes."""
    start_keys = [
        "timeline_start",
        "timeline_start_seconds",
        "start",
        "start_seconds",
        "source_start",
        "source_start_seconds",
    ]
    end_keys = [
        "timeline_end",
        "timeline_end_seconds",
        "end",
        "end_seconds",
        "source_end",
        "source_end_seconds",
    ]

    start = None
    end = None
    for key in start_keys:
        if key in obj and obj.get(key) is not None:
            start = safe_float(obj.get(key), None)  # type: ignore[arg-type]
            break
    for key in end_keys:
        if key in obj and obj.get(key) is not None:
            end = safe_float(obj.get(key), None)  # type: ignore[arg-type]
            break

    if start is None:
        for key in ("timeline_start_frame", "start_frame", "source_start_frame"):
            if key in obj and obj.get(key) is not None:
                start = safe_float(obj.get(key), 0.0) / max(1e-6, fps)
                break

    if end is None:
        for key in ("timeline_end_frame", "end_frame", "source_end_frame"):
            if key in obj and obj.get(key) is not None:
                end = safe_float(obj.get(key), 0.0) / max(1e-6, fps)
                break

    if end is None and start is not None:
        duration = None
        for key in ("duration", "duration_seconds", "timeline_duration", "timeline_duration_seconds"):
            if key in obj and obj.get(key) is not None:
                duration = safe_float(obj.get(key), None)  # type: ignore[arg-type]
                break
        if duration is None:
            for key in ("duration_frames", "timeline_duration_frames"):
                if key in obj and obj.get(key) is not None:
                    duration = safe_float(obj.get(key), 0.0) / max(1e-6, fps)
                    break
        if duration is not None:
            end = start + max(0.0, duration)

    return start, end


def srt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    ms_total = int(round(seconds * 1000.0))
    hours = ms_total // 3_600_000
    ms_total %= 3_600_000
    minutes = ms_total // 60_000
    ms_total %= 60_000
    secs = ms_total // 1000
    ms = ms_total % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    cs_total = int(round(seconds * 100.0))
    hours = cs_total // 360_000
    cs_total %= 360_000
    minutes = cs_total // 6_000
    cs_total %= 6_000
    secs = cs_total // 100
    cs = cs_total % 100
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def normalize_cues(
    raw_cues: Sequence[Dict[str, Any]],
    fps: float,
    min_duration_frames: int,
    prevent_overlap: bool,
    max_cues: int = 0,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    errors: List[Dict[str, Any]] = []
    cues: List[Dict[str, Any]] = []
    min_dur = max(0.001, float(min_duration_frames) / max(1e-6, fps))

    for idx, item in enumerate(raw_cues):
        if not isinstance(item, dict):
            errors.append({"index": idx, "error": "cue_not_object"})
            continue
        text = clean_text(item.get("text") or item.get("caption") or item.get("word") or "")
        if not text:
            errors.append({"index": idx, "error": "empty_text"})
            continue
        start, end = seconds_from_fields(item, fps=fps)
        if start is None:
            errors.append({"index": idx, "text": text, "error": "missing_start_time"})
            continue
        if end is None or end <= start:
            end = start + min_dur
        if end - start < min_dur:
            end = start + min_dur
        cues.append({
            "index": len(cues) + 1,
            "id": str(item.get("id") or item.get("subtitle_id") or f"sub_{len(cues)+1:04d}"),
            "text": text,
            "start": round(float(start), 4),
            "end": round(float(end), 4),
            "duration": round(float(end - start), 4),
            "source": item.get("source") or "generic_edit_commands.subtitle_clips",
            "raw": item if False else None,
        })

    cues.sort(key=lambda c: (c["start"], c["end"], c["index"]))

    if prevent_overlap and len(cues) > 1:
        for i in range(len(cues) - 1):
            cur = cues[i]
            nxt = cues[i + 1]
            if cur["end"] > nxt["start"]:
                target_end = max(cur["start"] + min_dur, nxt["start"] - (0.5 / max(1e-6, fps)))
                if target_end <= cur["start"]:
                    target_end = cur["start"] + min_dur
                cur["end"] = round(float(target_end), 4)
                cur["duration"] = round(float(cur["end"] - cur["start"]), 4)

    if max_cues and max_cues > 0:
        cues = cues[:max_cues]

    for idx, cue in enumerate(cues, start=1):
        cue["index"] = idx

    return cues, errors


# -----------------------------
# Generic edit command loading
# -----------------------------


def pick_fps(generic: Dict[str, Any], fallback: float = 24.0) -> float:
    paths = [
        ("fps",),
        ("timeline", "fps"),
        ("meta", "fps"),
        ("metadata", "fps"),
        ("source", "fps"),
        ("project", "fps"),
    ]
    for path in paths:
        obj: Any = generic
        ok = True
        for key in path:
            if isinstance(obj, dict) and key in obj:
                obj = obj[key]
            else:
                ok = False
                break
        if ok:
            fps = safe_float(obj, 0.0)
            if fps > 0:
                return fps
    return fallback


def extract_subtitle_clips(generic: Dict[str, Any], source: str = "auto") -> List[Dict[str, Any]]:
    if source in ("auto", "subtitle_clips"):
        clips = generic.get("subtitle_clips")
        if isinstance(clips, list) and clips:
            return [x for x in clips if isinstance(x, dict)]

    if source in ("auto", "commands"):
        out: List[Dict[str, Any]] = []
        commands = generic.get("commands") or generic.get("edit_commands") or []
        if isinstance(commands, list):
            for cmd in commands:
                if not isinstance(cmd, dict):
                    continue
                ops = cmd.get("operations") or cmd.get("ops") or []
                if not isinstance(ops, list):
                    continue
                for op in ops:
                    if not isinstance(op, dict):
                        continue
                    op_type = str(op.get("operation") or op.get("type") or "").lower()
                    if op_type in ("subtitle", "subtitle_clip", "caption", "caption_clip"):
                        out.append(op)
        if out:
            return out

    return []


# -----------------------------
# Style loading and mapping
# -----------------------------


def hex_to_rgb(hex_color: Any, fallback: Tuple[int, int, int] = (255, 255, 255)) -> Tuple[int, int, int]:
    if not isinstance(hex_color, str):
        return fallback
    s = hex_color.strip().lstrip("#")
    if len(s) != 6:
        return fallback
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except Exception:
        return fallback


def rgb_to_ass(hex_color: Any, alpha: int = 0, fallback: str = "#ffffff") -> str:
    # ASS color format: &HAABBGGRR
    r, g, b = hex_to_rgb(hex_color or fallback, hex_to_rgb(fallback))
    alpha = int(clamp(alpha, 0, 255))
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def color_luminance(hex_color: Any) -> float:
    r, g, b = hex_to_rgb(hex_color, (255, 255, 255))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def choose_profile(style_json: Dict[str, Any], profile_id: str = "primary") -> Dict[str, Any]:
    resolved = style_json.get("caption_style_resolved") or style_json.get("resolved") or {}
    profiles = style_json.get("caption_style_profiles") or style_json.get("style_profiles") or []

    if not isinstance(profiles, list):
        profiles = []

    if profile_id and profile_id not in ("primary", "auto"):
        for profile in profiles:
            if isinstance(profile, dict) and profile.get("style_id") == profile_id:
                return profile

    primary_id = resolved.get("primary_style_id") if isinstance(resolved, dict) else None
    if primary_id:
        for profile in profiles:
            if isinstance(profile, dict) and profile.get("style_id") == primary_id:
                return profile

    # Prefer dominant spoken caption profile.
    spoken = [p for p in profiles if isinstance(p, dict) and p.get("role") == "spoken_caption"]
    if spoken:
        return sorted(spoken, key=lambda p: (safe_int(p.get("sample_count"), 0), safe_float((p.get("confidence") or {}).get("score"), 0.0)), reverse=True)[0]

    if isinstance(resolved, dict) and resolved.get("available"):
        return resolved

    return {}


def profile_get(profile: Dict[str, Any], *path: str, default: Any = None) -> Any:
    obj: Any = profile
    for key in path:
        if isinstance(obj, dict) and key in obj:
            obj = obj[key]
        else:
            return default
    return obj


def build_style_contract(
    caption_style: Dict[str, Any],
    profile_id: str,
    font_name: str,
    font_scale: float,
    outline_scale: float,
    shadow_scale: float,
    play_res_x: int,
    play_res_y: int,
    default_anchor_y: float,
) -> Dict[str, Any]:
    profile = choose_profile(caption_style, profile_id=profile_id)
    resolved = caption_style.get("caption_style_resolved") or caption_style.get("resolved") or {}
    source_style = profile if profile else resolved if isinstance(resolved, dict) else {}

    placement = source_style.get("placement") or {}
    typography = source_style.get("typography") or {}
    colors = source_style.get("colors") or {}
    stroke = source_style.get("stroke") or {}
    shadow = source_style.get("shadow") or {}

    anchor = placement.get("anchor") or {}
    anchor_x = clamp(safe_float(anchor.get("x"), 0.5), 0.0, 1.0)
    anchor_y = clamp(safe_float(anchor.get("y"), default_anchor_y), 0.0, 1.0)

    font_px = typography.get("font_height_px")
    font_ratio = typography.get("font_height_ratio")
    if font_px is None and font_ratio is not None:
        font_px = safe_float(font_ratio, 0.031) * play_res_y
    if font_px is None:
        font_px = 60
    font_size = int(round(clamp(safe_float(font_px, 60.0) * font_scale, 12, 260)))

    fill = colors.get("fill") or "#ffffff"
    outline = colors.get("stroke") or stroke.get("color") or "#000000"
    shadow_color = colors.get("shadow") or shadow.get("color") or outline

    # Guardrail: regular spoken captions should usually be light fill + dark outline.
    # If detector output is inverted, fix it.
    if color_luminance(fill) < 90 and color_luminance(outline) > 170:
        fill, outline = outline, fill
    if color_luminance(fill) < 120 and color_luminance(shadow_color) > 170:
        shadow_color = "#000000"

    outline_px = stroke.get("width_px_estimate")
    if outline_px is None:
        outline_px = max(2, int(round(font_size * 0.055)))
    outline_px = int(round(clamp(safe_float(outline_px, 3.0) * outline_scale, 0, 30)))

    shadow_px = shadow.get("blur_px_estimate")
    if shadow_px is None:
        shadow_px = 2 if bool(shadow.get("enabled", True)) else 0
    shadow_px = int(round(clamp(safe_float(shadow_px, 2.0) * shadow_scale, 0, 20)))

    font_weight = str(typography.get("font_weight") or "bold").lower()
    bold = bool("bold" in font_weight or "semi" in font_weight)
    italic = bool("italic" in str(typography.get("font_style") or "").lower())

    role = source_style.get("role") or "spoken_caption"
    style_id = source_style.get("style_id") or resolved.get("primary_style_id") or "resolved_primary"

    return {
        "style_id": style_id,
        "role": role,
        "font_name": font_name,
        "font_size": font_size,
        "bold": bold,
        "italic": italic,
        "fill": fill,
        "outline": outline,
        "shadow": shadow_color,
        "outline_px": outline_px,
        "shadow_px": shadow_px,
        "anchor": {
            "x": round(anchor_x, 4),
            "y": round(anchor_y, 4),
            "pixel_x": int(round(anchor_x * play_res_x)),
            "pixel_y": int(round(anchor_y * play_res_y)),
        },
        "placement": placement,
        "typography": typography,
        "source_profile": source_style,
    }


# -----------------------------
# File writers
# -----------------------------


def escape_srt_text(text: str) -> str:
    return clean_text(text)


def escape_ass_text(text: str) -> str:
    text = clean_text(text)
    # Braces start override tags in ASS. Replace rather than escaping to keep players safe.
    text = text.replace("{", "(").replace("}", ")")
    text = text.replace("\\", "\\\\")
    return text.replace("\n", r"\N")


def write_srt(path: str, cues: Sequence[Dict[str, Any]], encoding: str = "utf-8-sig") -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    lines: List[str] = []
    for idx, cue in enumerate(cues, start=1):
        lines.append(str(idx))
        lines.append(f"{srt_time(cue['start'])} --> {srt_time(cue['end'])}")
        lines.append(escape_srt_text(cue["text"]))
        lines.append("")
    with open(path, "w", encoding=encoding) as f:
        f.write("\n".join(lines))


def write_ass(
    path: str,
    cues: Sequence[Dict[str, Any]],
    style: Dict[str, Any],
    play_res_x: int,
    play_res_y: int,
    include_position_override: bool = True,
    encoding: str = "utf-8-sig",
) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    primary = rgb_to_ass(style["fill"], alpha=0, fallback="#ffffff")
    secondary = rgb_to_ass("#ffffff", alpha=0, fallback="#ffffff")
    outline = rgb_to_ass(style["outline"], alpha=0, fallback="#000000")
    back = rgb_to_ass(style["shadow"], alpha=80, fallback="#000000")

    bold = -1 if style.get("bold") else 0
    italic = -1 if style.get("italic") else 0
    font_size = safe_int(style.get("font_size"), 60)
    outline_px = safe_float(style.get("outline_px"), 3.0)
    shadow_px = safe_float(style.get("shadow_px"), 2.0)

    # Alignment 5 = centered at explicit \pos(x,y). This mirrors viral caption overlays better
    # than bottom-aligned subtitle defaults.
    alignment = 5

    header = f"""[Script Info]
; Generated by Video Cloner {VERSION}
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {play_res_x}
PlayResY: {play_res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: VC_Main,{style['font_name']},{font_size},{primary},{secondary},{outline},{back},{bold},{italic},0,0,100,100,0,0,1,{outline_px:.2f},{shadow_px:.2f},{alignment},10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    x = safe_int((style.get("anchor") or {}).get("pixel_x"), int(play_res_x * 0.5))
    y = safe_int((style.get("anchor") or {}).get("pixel_y"), int(play_res_y * 0.70))
    tag = rf"{{\an5\pos({x},{y})}}" if include_position_override else ""

    lines = [header.rstrip()]
    for cue in cues:
        text = escape_ass_text(cue["text"])
        lines.append(f"Dialogue: 0,{ass_time(cue['start'])},{ass_time(cue['end'])},VC_Main,,0,0,0,,{tag}{text}")

    with open(path, "w", encoding=encoding) as f:
        f.write("\n".join(lines) + "\n")


# -----------------------------
# Main
# -----------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile Video Cloner subtitle clips into styled DaVinci subtitle files.")

    parser.add_argument("--generic", required=True, help="Path to generic_edit_commands.json")
    parser.add_argument("--caption-style", required=True, help="Path to detect_caption_style.py output JSON")

    parser.add_argument("--output-ass", required=True, help="Styled ASS subtitle output path")
    parser.add_argument("--output-srt", default=None, help="Fallback SRT output path. If omitted, same stem as ASS with .srt")
    parser.add_argument("--report", default=None, help="JSON report output path. If omitted, same stem as ASS with _report.json")

    parser.add_argument("--source", choices=["auto", "subtitle_clips", "commands"], default="auto")
    parser.add_argument("--profile-id", default="primary", help="Style profile id to use, or primary/auto")
    parser.add_argument("--max-cues", type=int, default=0, help="0 = all cues")

    parser.add_argument("--fps", type=float, default=0.0, help="Override FPS. Default: read from generic JSON, fallback 24")
    parser.add_argument("--play-res-x", type=int, default=1080)
    parser.add_argument("--play-res-y", type=int, default=1920)

    parser.add_argument("--font-name", default="Arial", help="ASS font name. Use an installed font on your Resolve machine.")
    parser.add_argument("--font-scale", type=float, default=1.0)
    parser.add_argument("--outline-scale", type=float, default=1.0)
    parser.add_argument("--shadow-scale", type=float, default=1.0)
    parser.add_argument("--default-anchor-y", type=float, default=0.6875)

    parser.add_argument("--min-duration-frames", type=int, default=1)
    parser.add_argument("--prevent-overlap", type=str2bool, default=True)
    parser.add_argument("--include-ass-position-override", type=str2bool, default=True)
    parser.add_argument("--encoding", default="utf-8-sig", choices=["utf-8", "utf-8-sig"])

    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    generic_path = os.path.abspath(args.generic)
    caption_style_path = os.path.abspath(args.caption_style)
    output_ass = os.path.abspath(args.output_ass)
    output_srt = os.path.abspath(args.output_srt) if args.output_srt else str(Path(output_ass).with_suffix(".srt"))
    report_path = os.path.abspath(args.report) if args.report else str(Path(output_ass).with_name(Path(output_ass).stem + "_report.json"))

    generic = load_json(generic_path)
    caption_style = load_json(caption_style_path)

    fps = float(args.fps) if args.fps and args.fps > 0 else pick_fps(generic, fallback=24.0)
    raw_cues = extract_subtitle_clips(generic, source=args.source)
    cues, cue_errors = normalize_cues(
        raw_cues,
        fps=fps,
        min_duration_frames=args.min_duration_frames,
        prevent_overlap=bool(args.prevent_overlap),
        max_cues=args.max_cues,
    )

    style_contract = build_style_contract(
        caption_style=caption_style,
        profile_id=args.profile_id,
        font_name=args.font_name,
        font_scale=args.font_scale,
        outline_scale=args.outline_scale,
        shadow_scale=args.shadow_scale,
        play_res_x=args.play_res_x,
        play_res_y=args.play_res_y,
        default_anchor_y=args.default_anchor_y,
    )

    write_srt(output_srt, cues, encoding=args.encoding)
    write_ass(
        output_ass,
        cues,
        style=style_contract,
        play_res_x=args.play_res_x,
        play_res_y=args.play_res_y,
        include_position_override=bool(args.include_ass_position_override),
        encoding=args.encoding,
    )

    wc = [word_count(c["text"]) for c in cues]
    avg_words = sum(wc) / max(1, len(wc))
    word_level_likely = bool(cues and avg_words <= 1.25)

    report = {
        "success": True,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "inputs": {
            "generic": generic_path,
            "caption_style": caption_style_path,
            "source": args.source,
            "profile_id": args.profile_id,
        },
        "outputs": {
            "ass": output_ass,
            "srt": output_srt,
            "report": report_path,
        },
        "timing": {
            "fps": fps,
            "cue_count": len(cues),
            "raw_cue_count": len(raw_cues),
            "min_duration_frames": args.min_duration_frames,
            "prevent_overlap": bool(args.prevent_overlap),
            "max_cues": args.max_cues,
            "word_level_likely": word_level_likely,
            "avg_words_per_cue": round(avg_words, 4),
            "first_cue": cues[0] if cues else None,
            "last_cue": cues[-1] if cues else None,
        },
        "style": {
            "ass_style_name": "VC_Main",
            "play_res_x": args.play_res_x,
            "play_res_y": args.play_res_y,
            "style_contract": style_contract,
            "resolve_manual_style_hint": {
                "note": "SRT is safest for Resolve subtitle track timing. Use this style as the manual/API style target if Resolve does not preserve ASS styling on import.",
                "font_name": style_contract.get("font_name"),
                "font_size_px": style_contract.get("font_size"),
                "fill": style_contract.get("fill"),
                "outline": style_contract.get("outline"),
                "outline_px": style_contract.get("outline_px"),
                "shadow": style_contract.get("shadow"),
                "shadow_px": style_contract.get("shadow_px"),
                "anchor": style_contract.get("anchor"),
            },
        },
        "compatibility": {
            "srt": "Resolve-native timing fallback; limited styling.",
            "ass": "Style-rich subtitle source. If Resolve does not preserve ASS styling in your version/workflow, use the report JSON as the style contract for a Resolve/Text+/OpenReel adapter.",
        },
        "errors": cue_errors[:50],
        "errors_count": len(cue_errors),
    }

    write_json(report_path, report)

    stdout = {
        "success": True,
        "version": VERSION,
        "ass": output_ass,
        "srt": output_srt,
        "report": report_path,
        "cue_count": len(cues),
        "word_level_likely": word_level_likely,
        "avg_words_per_cue": round(avg_words, 4),
        "style_id": style_contract.get("style_id"),
        "fill": style_contract.get("fill"),
        "outline": style_contract.get("outline"),
        "font_size": style_contract.get("font_size"),
        "anchor": style_contract.get("anchor"),
        "errors_count": len(cue_errors),
    }
    print(json.dumps(stdout, ensure_ascii=False))


if __name__ == "__main__":
    main()
