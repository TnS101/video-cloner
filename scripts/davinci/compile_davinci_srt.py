#!/usr/bin/env python3
"""
compile_davinci_srt.py

Video Cloner -> DaVinci Resolve subtitle compiler.

Purpose:
    Convert generic_edit_commands.json subtitle_clips into a standard .srt file
    that can be imported into DaVinci Resolve as a native subtitle track.

Why this exists:
    Resolve Text+/Fusion title insertion through the scripting API is unreliable
    for exact per-word timing and track placement. A native SRT subtitle track is
    safer for:
        - one-word captions
        - exact subtitle timing
        - avoiding timeline ripple/push of V1/A1
        - keeping subtitles in a dedicated subtitle layer

Expected input:
    generic_edit_commands.json produced by scripts/planning/compile_generic_edit.py
    with top-level timeline commands and/or subtitle_clips.

Recommended usage:
    python compile_davinci_srt.py \
      --generic path/to/generic_edit_commands.json \
      --output path/to/video_word_subtitles.srt \
      --report path/to/video_word_subtitles_report.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

VERSION = "davinci_srt_compiler_v1_0_word_subtitles"
SCHEMA = "video_cloner_davinci_srt"
SCHEMA_VERSION = "1.0"


# -----------------------------
# Basic helpers
# -----------------------------


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: Dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now_unix() -> float:
    return round(time.time(), 3)


def get_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        return float(value)
    except Exception:
        return default


def get_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        return int(round(float(value)))
    except Exception:
        return default


def truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def ensure_parent(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def clean_text(text: Any) -> str:
    """Normalize subtitle text without destroying punctuation/case."""
    if text is None:
        return ""
    text = str(text)
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    # SRT parsers can interpret bare arrows as cue separators.
    text = text.replace("-->", "→")
    return text


def srt_escape_text(text: str) -> str:
    """Keep SRT text simple and single-line by default."""
    return clean_text(text)


def safe_filename_stem(path: str) -> str:
    try:
        return Path(path).stem
    except Exception:
        return "subtitles"


# -----------------------------
# Timing helpers
# -----------------------------


def seconds_to_srt_timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    total_ms = int(round(seconds * 1000.0))
    hours = total_ms // 3_600_000
    rem = total_ms % 3_600_000
    minutes = rem // 60_000
    rem = rem % 60_000
    secs = rem // 1000
    ms = rem % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def frame_to_seconds(frame: int, fps: float) -> float:
    fps = fps if fps and fps > 0 else 24.0
    return max(0.0, float(frame) / float(fps))


def seconds_to_frame(seconds: float, fps: float) -> int:
    fps = fps if fps and fps > 0 else 24.0
    return max(0, int(round(float(seconds or 0.0) * float(fps))))


def get_fps(generic: Dict[str, Any], override_fps: Optional[float] = None) -> float:
    if override_fps and override_fps > 0:
        return float(override_fps)
    source = generic.get("source") if isinstance(generic.get("source"), dict) else {}
    fps = get_float(source.get("fps"), 0.0)
    if fps <= 0:
        meta = generic.get("_meta") if isinstance(generic.get("_meta"), dict) else {}
        fps = get_float(meta.get("fps"), 0.0)
    return fps if fps > 0 else 24.0


def normalize_clip_timing(raw: Dict[str, Any], fps: float) -> Tuple[int, int, float, float, Dict[str, Any]]:
    """
    Return relative start/end frames and seconds for an input subtitle clip.

    The generic pipeline should store relative timeline frames/seconds, not Resolve's
    absolute 01:00:00:00 frame. This compiler intentionally emits SRT from 00:00:00.
    """
    debug: Dict[str, Any] = {}

    start_frame_candidates = [
        raw.get("timeline_start_frame"),
        raw.get("start_frame"),
        raw.get("frame_start"),
        raw.get("source_start_frame"),
    ]
    end_frame_candidates = [
        raw.get("timeline_end_frame"),
        raw.get("end_frame"),
        raw.get("frame_end"),
        raw.get("source_end_frame"),
    ]

    start_seconds_candidates = [
        raw.get("timeline_start"),
        raw.get("timeline_start_seconds"),
        raw.get("start"),
        raw.get("start_seconds"),
    ]
    end_seconds_candidates = [
        raw.get("timeline_end"),
        raw.get("timeline_end_seconds"),
        raw.get("end"),
        raw.get("end_seconds"),
    ]

    start_frame = None
    end_frame = None

    for value in start_frame_candidates:
        if value is not None:
            start_frame = get_int(value, 0)
            debug["start_source"] = "frame"
            break

    for value in end_frame_candidates:
        if value is not None:
            end_frame = get_int(value, 0)
            debug["end_source"] = "frame"
            break

    start_seconds = None
    end_seconds = None

    for value in start_seconds_candidates:
        if value is not None:
            start_seconds = get_float(value, 0.0)
            debug.setdefault("start_source", "seconds")
            break

    for value in end_seconds_candidates:
        if value is not None:
            end_seconds = get_float(value, 0.0)
            debug.setdefault("end_source", "seconds")
            break

    if start_frame is None and start_seconds is not None:
        start_frame = seconds_to_frame(start_seconds, fps)
    if end_frame is None and end_seconds is not None:
        end_frame = seconds_to_frame(end_seconds, fps)

    if start_frame is None:
        start_frame = 0
    if end_frame is None:
        duration_frames = get_int(raw.get("duration_frames"), 0)
        if duration_frames <= 0:
            duration_seconds = get_float(raw.get("duration"), get_float(raw.get("duration_seconds"), 0.0))
            duration_frames = max(1, seconds_to_frame(duration_seconds, fps)) if duration_seconds > 0 else 1
        end_frame = start_frame + max(1, duration_frames)

    start_frame = max(0, start_frame)
    end_frame = max(start_frame + 1, end_frame)
    start_seconds_f = frame_to_seconds(start_frame, fps)
    end_seconds_f = frame_to_seconds(end_frame, fps)

    return start_frame, end_frame, start_seconds_f, end_seconds_f, debug


# -----------------------------
# Subtitle source extraction
# -----------------------------


def extract_top_level_subtitle_clips(generic: Dict[str, Any]) -> List[Dict[str, Any]]:
    value = generic.get("subtitle_clips")
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]

    timeline_obj = generic.get("timeline")
    if isinstance(timeline_obj, dict):
        value = timeline_obj.get("subtitle_clips")
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]

    return []


def extract_subtitle_ops_from_timeline(generic: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    timeline = generic.get("timeline")
    if not isinstance(timeline, list):
        return out

    for cmd in timeline:
        if not isinstance(cmd, dict):
            continue
        for op in cmd.get("operations") or []:
            if not isinstance(op, dict):
                continue
            if op.get("operation") not in {"subtitle", "subtitle_clip", "caption", "text"}:
                continue
            params = op.get("parameters") if isinstance(op.get("parameters"), dict) else {}
            merged = dict(params)
            merged.setdefault("command_id", cmd.get("command_id"))
            merged.setdefault("shot_id", cmd.get("shot_id"))
            out.append(merged)
    return out


def extract_transcript_words(generic: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fallback: build subtitles from transcript words if available in generic payload."""
    candidates: List[Dict[str, Any]] = []

    def visit(obj: Any) -> None:
        if isinstance(obj, dict):
            words = obj.get("words")
            if isinstance(words, list):
                for w in words:
                    if not isinstance(w, dict):
                        continue
                    text = clean_text(w.get("word") or w.get("text"))
                    if not text:
                        continue
                    start = w.get("start") if w.get("start") is not None else w.get("start_seconds")
                    end = w.get("end") if w.get("end") is not None else w.get("end_seconds")
                    if start is None or end is None:
                        continue
                    candidates.append({
                        "id": w.get("id") or w.get("index") or f"word_{len(candidates) + 1:04d}",
                        "text": text,
                        "start": get_float(start, 0.0),
                        "end": get_float(end, 0.0),
                        "source": "transcript_words_fallback",
                    })
            for value in obj.values():
                visit(value)
        elif isinstance(obj, list):
            for value in obj:
                visit(value)

    # Keep traversal bounded enough for this project-size JSON.
    visit(generic.get("transcript"))
    if not candidates:
        visit(generic.get("source"))
    return candidates


def extract_transcript_segments(generic: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    def maybe_segments(obj: Any) -> None:
        if not isinstance(obj, dict):
            return
        segments = obj.get("segments")
        if not isinstance(segments, list):
            return
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            text = clean_text(seg.get("text"))
            if not text:
                continue
            start = seg.get("start") if seg.get("start") is not None else seg.get("start_seconds")
            end = seg.get("end") if seg.get("end") is not None else seg.get("end_seconds")
            if start is None or end is None:
                continue
            candidates.append({
                "id": seg.get("id") or f"seg_{len(candidates) + 1:04d}",
                "text": text,
                "start": get_float(start, 0.0),
                "end": get_float(end, 0.0),
                "source": "transcript_segments_fallback",
            })

    maybe_segments(generic.get("transcript"))
    source = generic.get("source") if isinstance(generic.get("source"), dict) else {}
    maybe_segments(source.get("transcript") if isinstance(source.get("transcript"), dict) else {})
    return candidates


def choose_subtitle_source(generic: Dict[str, Any], source_mode: str) -> Tuple[str, List[Dict[str, Any]]]:
    source_mode = str(source_mode or "auto").lower().strip()

    top = extract_top_level_subtitle_clips(generic)
    ops = extract_subtitle_ops_from_timeline(generic)
    words = extract_transcript_words(generic)
    segments = extract_transcript_segments(generic)

    if source_mode == "subtitle_clips":
        return "subtitle_clips", top
    if source_mode == "operations":
        return "timeline_operations", ops
    if source_mode == "words":
        return "transcript_words", words
    if source_mode == "segments":
        return "transcript_segments", segments

    # Auto: prefer the compiler's final subtitle_clips because they already know
    # whether the user requested word-level captions.
    if top:
        return "subtitle_clips", top
    if ops:
        return "timeline_operations", ops
    if words:
        return "transcript_words", words
    if segments:
        return "transcript_segments", segments
    return "none", []


# -----------------------------
# SRT cue compilation
# -----------------------------


def normalize_cues(
    raw_subtitles: List[Dict[str, Any]],
    fps: float,
    min_duration_frames: int = 1,
    max_duration_frames: int = 0,
    start_offset_frames: int = 0,
    prevent_overlap: bool = True,
    max_subtitles: int = 0,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    cues: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    min_duration_frames = max(1, int(min_duration_frames or 1))
    max_duration_frames = max(0, int(max_duration_frames or 0))
    start_offset_frames = int(start_offset_frames or 0)

    for idx, raw in enumerate(raw_subtitles, start=1):
        text = clean_text(raw.get("text") or raw.get("word") or raw.get("caption"))
        if not text:
            skipped.append({"index": idx, "reason": "empty_text", "raw_id": raw.get("id")})
            continue

        start_frame, end_frame, _, _, timing_debug = normalize_clip_timing(raw, fps)
        start_frame = max(0, start_frame + start_offset_frames)
        end_frame = max(start_frame + 1, end_frame + start_offset_frames)

        requested_duration = end_frame - start_frame
        if requested_duration < min_duration_frames:
            end_frame = start_frame + min_duration_frames
        if max_duration_frames > 0 and (end_frame - start_frame) > max_duration_frames:
            end_frame = start_frame + max_duration_frames

        cue = {
            "index": len(cues) + 1,
            "id": raw.get("id") or raw.get("subtitle_id") or f"sub_{len(cues) + 1:04d}",
            "text": text,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "duration_frames": max(1, end_frame - start_frame),
            "source": raw.get("source"),
            "raw_index": idx,
            "timing_debug": timing_debug,
        }
        cues.append(cue)

        if max_subtitles and len(cues) >= max_subtitles:
            break

    cues.sort(key=lambda c: (c["start_frame"], c["end_frame"], c["index"]))

    adjustments: List[Dict[str, Any]] = []
    if prevent_overlap:
        for i, cue in enumerate(cues):
            if i + 1 >= len(cues):
                continue
            nxt = cues[i + 1]
            if cue["end_frame"] > nxt["start_frame"]:
                old_end = cue["end_frame"]
                cue["end_frame"] = max(cue["start_frame"] + 1, nxt["start_frame"])
                cue["duration_frames"] = max(1, cue["end_frame"] - cue["start_frame"])
                adjustments.append({
                    "cue_id": cue.get("id"),
                    "reason": "prevent_overlap",
                    "old_end_frame": old_end,
                    "new_end_frame": cue["end_frame"],
                    "next_start_frame": nxt["start_frame"],
                })

    # Drop cues that became invalid after overlap prevention.
    final_cues: List[Dict[str, Any]] = []
    for cue in cues:
        if cue["end_frame"] <= cue["start_frame"]:
            skipped.append({"index": cue.get("raw_index"), "reason": "invalid_after_overlap", "raw_id": cue.get("id")})
            continue
        cue["index"] = len(final_cues) + 1
        cue["start_seconds"] = frame_to_seconds(cue["start_frame"], fps)
        cue["end_seconds"] = frame_to_seconds(cue["end_frame"], fps)
        cue["duration_seconds"] = round(cue["end_seconds"] - cue["start_seconds"], 6)
        cue["srt_start"] = seconds_to_srt_timestamp(cue["start_seconds"])
        cue["srt_end"] = seconds_to_srt_timestamp(cue["end_seconds"])
        final_cues.append(cue)

    stats = {
        "raw_count": len(raw_subtitles),
        "cue_count": len(final_cues),
        "skipped_count": len(skipped),
        "adjustments_count": len(adjustments),
        "first_start_seconds": final_cues[0]["start_seconds"] if final_cues else None,
        "last_end_seconds": final_cues[-1]["end_seconds"] if final_cues else None,
        "word_level_likely": bool(final_cues) and (sum(len(c["text"].split()) for c in final_cues) / max(1, len(final_cues)) <= 1.15),
        "avg_words_per_cue": round(sum(len(c["text"].split()) for c in final_cues) / max(1, len(final_cues)), 4) if final_cues else 0.0,
    }

    return final_cues, skipped, {"adjustments": adjustments, "stats": stats}


def cues_to_srt(cues: List[Dict[str, Any]]) -> str:
    blocks: List[str] = []
    for i, cue in enumerate(cues, start=1):
        text = srt_escape_text(cue.get("text", ""))
        if not text:
            continue
        blocks.append(
            f"{i}\n{cue['srt_start']} --> {cue['srt_end']}\n{text}"
        )
    return "\n\n".join(blocks).strip() + ("\n" if blocks else "")


def write_srt(path: str, cues: List[Dict[str, Any]], encoding: str = "utf-8-sig") -> None:
    ensure_parent(path)
    text = cues_to_srt(cues)
    with open(path, "w", encoding=encoding, newline="\n") as f:
        f.write(text)


# -----------------------------
# CLI
# -----------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Compile Video Cloner subtitle_clips to DaVinci-importable SRT.")
    p.add_argument("--generic", required=True, help="Path to generic_edit_commands.json")
    p.add_argument("--output", required=True, help="Output .srt path")
    p.add_argument("--report", default=None, help="Optional JSON report path")
    p.add_argument("--fps", type=float, default=None, help="Override FPS. Defaults to generic.source.fps")
    p.add_argument(
        "--source",
        default="auto",
        choices=["auto", "subtitle_clips", "operations", "words", "segments"],
        help="Subtitle source. Use auto/subtitle_clips for normal pipeline output.",
    )
    p.add_argument("--min-duration-frames", type=int, default=1, help="Minimum subtitle cue duration in frames.")
    p.add_argument("--max-duration-frames", type=int, default=0, help="Optional max cue duration in frames. 0 disables.")
    p.add_argument("--start-offset-frames", type=int, default=0, help="Optional timing offset in frames. Usually 0.")
    p.add_argument("--prevent-overlap", default="true", help="Prevent overlapping SRT cues: true/false")
    p.add_argument("--max-subtitles", type=int, default=0, help="Limit number of cues for testing. 0 = all.")
    p.add_argument("--encoding", default="utf-8-sig", choices=["utf-8", "utf-8-sig"], help="SRT text encoding.")
    p.add_argument("--dry-run", action="store_true", help="Build report but do not write SRT.")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    started = time.time()
    generic_path = str(Path(args.generic).resolve())
    output_path = str(Path(args.output).resolve())
    report_path = str(Path(args.report).resolve()) if args.report else str(Path(output_path).with_suffix(".report.json"))

    report: Dict[str, Any] = {
        "success": False,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "compiler_version": VERSION,
        "created_at_unix": now_unix(),
        "input": {"generic": generic_path},
        "output": {"srt": output_path, "report": report_path},
        "options": {
            "source": args.source,
            "fps_override": args.fps,
            "min_duration_frames": args.min_duration_frames,
            "max_duration_frames": args.max_duration_frames,
            "start_offset_frames": args.start_offset_frames,
            "prevent_overlap": truthy(args.prevent_overlap, True),
            "max_subtitles": args.max_subtitles,
            "encoding": args.encoding,
            "dry_run": bool(args.dry_run),
        },
        "summary": {},
        "errors": [],
        "warnings": [],
    }

    try:
        generic = load_json(generic_path)
        fps = get_fps(generic, args.fps)
        selected_source, raw_subtitles = choose_subtitle_source(generic, args.source)

        report["source"] = {
            "selected": selected_source,
            "raw_subtitles_count": len(raw_subtitles),
            "generic_schema": generic.get("schema"),
            "generic_success": generic.get("success"),
            "generic_compiler_version": generic.get("compiler_version"),
            "fps": fps,
        }

        if not raw_subtitles:
            report["errors"].append(f"No subtitles found from source mode: {args.source}")
            save_json(report_path, report)
            print(json.dumps(report, ensure_ascii=False))
            return 2

        cues, skipped, extra = normalize_cues(
            raw_subtitles=raw_subtitles,
            fps=fps,
            min_duration_frames=args.min_duration_frames,
            max_duration_frames=args.max_duration_frames,
            start_offset_frames=args.start_offset_frames,
            prevent_overlap=truthy(args.prevent_overlap, True),
            max_subtitles=max(0, args.max_subtitles),
        )

        if not cues:
            report["errors"].append("Subtitle source was found, but zero valid SRT cues were produced.")
            report["skipped"] = skipped[:200]
            save_json(report_path, report)
            print(json.dumps(report, ensure_ascii=False))
            return 3

        if not args.dry_run:
            write_srt(output_path, cues, encoding=args.encoding)

        report["success"] = True
        report["summary"] = {
            **extra.get("stats", {}),
            "srt_written": not args.dry_run,
            "output_exists": Path(output_path).exists() if not args.dry_run else False,
            "runtime_seconds": round(time.time() - started, 3),
        }
        report["timing"] = {
            "fps": fps,
            "start_offset_frames": args.start_offset_frames,
            "prevent_overlap": truthy(args.prevent_overlap, True),
            "min_duration_frames": args.min_duration_frames,
            "max_duration_frames": args.max_duration_frames,
        }
        report["sample_cues"] = cues[:10]
        report["skipped"] = skipped[:200]
        report["adjustments"] = extra.get("adjustments", [])[:200]

        save_json(report_path, report)
        print(json.dumps({
            "success": True,
            "compiler_version": VERSION,
            "source_selected": selected_source,
            "srt": output_path,
            "report": report_path,
            "cue_count": len(cues),
            "word_level_likely": report["summary"].get("word_level_likely"),
            "avg_words_per_cue": report["summary"].get("avg_words_per_cue"),
            "runtime_seconds": report["summary"].get("runtime_seconds"),
        }, ensure_ascii=False))
        return 0

    except Exception as exc:
        report["errors"].append({"type": type(exc).__name__, "error": str(exc)})
        try:
            save_json(report_path, report)
        except Exception:
            pass
        print(json.dumps(report, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
