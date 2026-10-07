#!/usr/bin/env python3
"""
transcribe.py

Video Cloner transcript layer.

Purpose:
    Produce a stable, caption-ready transcript JSON for the editor-agnostic
    pipeline. This script is intentionally analyzer-only: it does not create
    Resolve subtitles or editor commands.

Output is designed for:
    - merge_analysis.py
    - compile_generic_edit.py subtitle_clips
    - future Resolve Text+/subtitle controller

Backward-compatible invocation examples:
    python transcribe.py input.wav
    python transcribe.py input.wav output.json medium cuda float16
    python transcribe.py input.wav --output output.json --model medium --device cuda --compute-type float16
"""

from __future__ import annotations

import argparse
import json
import os
import re
import site
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

VERSION = "transcribe_faster_whisper_caption_ready_v3"
SCHEMA = "video_cloner_transcript"
SCHEMA_VERSION = "2.0"


# -------------------------
# JSON / failure helpers
# -------------------------


def print_json(data: Dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False), flush=True)


def fail(message: str, extra: Optional[Dict[str, Any]] = None, exit_code: int = 1) -> None:
    payload: Dict[str, Any] = {
        "success": False,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "error": message,
    }
    if extra:
        payload.update(extra)
    print_json(payload)
    sys.exit(exit_code)


# -------------------------
# Path / CUDA DLL bootstrap
# -------------------------


def unique_paths(paths: Iterable[Any]) -> List[Path]:
    seen = set()
    out: List[Path] = []
    for p in paths:
        if not p:
            continue
        try:
            pp = Path(p).expanduser().resolve()
        except Exception:
            continue
        key = str(pp).lower()
        if key not in seen:
            seen.add(key)
            out.append(pp)
    return out


def get_site_package_roots() -> List[Path]:
    roots: List[Path] = []

    # Correct venv: the interpreter used to run this script.
    roots.append(Path(sys.prefix) / "Lib" / "site-packages")
    roots.append(Path(sys.base_prefix) / "Lib" / "site-packages")

    try:
        roots.extend(Path(p) for p in site.getsitepackages())
    except Exception:
        pass

    try:
        user_site = site.getusersitepackages()
        if user_site:
            roots.append(Path(user_site))
    except Exception:
        pass

    # Optional explicit override for n8n/Windows debugging.
    env_root = os.environ.get("VIDEO_CLONER_AUDIO_SITE_PACKAGES")
    if env_root:
        roots.append(Path(env_root))

    return [p for p in unique_paths(roots) if p.exists()]


def collect_cuda_dll_dirs() -> List[Path]:
    site_roots = get_site_package_roots()
    candidates: List[Path] = []

    for sp in site_roots:
        nvidia = sp / "nvidia"
        candidates.extend([
            nvidia / "cublas" / "bin",
            nvidia / "cudnn" / "bin",
            nvidia / "cuda_runtime" / "bin",
            nvidia / "cuda_nvrtc" / "bin",
            nvidia / "cuda_cupti" / "bin",
        ])

        # Robust fallback: add every directory under site-packages/nvidia that contains DLLs.
        if nvidia.exists():
            try:
                for dll in nvidia.rglob("*.dll"):
                    candidates.append(dll.parent)
            except Exception:
                pass

    return [p for p in unique_paths(candidates) if p.exists()]


CUDA_DLL_DIRS = collect_cuda_dll_dirs()
EXISTING_DLL_DIRS: List[str] = []
DLL_ADD_ERRORS: List[Dict[str, str]] = []

for dll_dir in CUDA_DLL_DIRS:
    try:
        EXISTING_DLL_DIRS.append(str(dll_dir))
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(dll_dir))
    except Exception as exc:
        DLL_ADD_ERRORS.append({"path": str(dll_dir), "error": str(exc)})

if EXISTING_DLL_DIRS:
    os.environ["PATH"] = ";".join(EXISTING_DLL_DIRS) + ";" + os.environ.get("PATH", "")


def dll_exists(filename: str) -> Optional[str]:
    for folder in CUDA_DLL_DIRS:
        candidate = folder / filename
        if candidate.exists():
            return str(candidate)
    return None


def find_any_dll_contains(partial_name: str) -> List[str]:
    partial = partial_name.lower()
    found: List[str] = []
    for folder in CUDA_DLL_DIRS:
        try:
            for file in folder.glob("*.dll"):
                if partial in file.name.lower():
                    found.append(str(file))
        except Exception:
            pass
    return found[:20]


def cuda_diagnostics() -> Dict[str, Any]:
    return {
        "cublas64_12.dll": dll_exists("cublas64_12.dll"),
        "cudnn": (
            dll_exists("cudnn_ops64_9.dll")
            or dll_exists("cudnn64_9.dll")
            or dll_exists("cudnn64_8.dll")
        ),
        "cudart64_12.dll": dll_exists("cudart64_12.dll"),
        "existing_dll_dirs_count": len(EXISTING_DLL_DIRS),
        "dll_add_errors": DLL_ADD_ERRORS,
    }


# -------------------------
# Arg parsing
# -------------------------


def str_to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_args(argv: List[str]) -> argparse.Namespace:
    if len(argv) < 2:
        fail(
            "Missing input video/audio path",
            {"usage": "transcribe.py <input> [output.json] [model] [device] [compute_type]"},
        )

    parser = argparse.ArgumentParser(description="Transcribe audio/video into caption-ready JSON.")
    parser.add_argument("input", help="Input audio/video path")
    parser.add_argument("positional", nargs="*", help="Backward-compatible positional args")

    parser.add_argument("--output", default=None, help="Output transcript JSON path")
    parser.add_argument("--model", default="medium", help="faster-whisper model size/name. Default: medium")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu", "auto"], help="Inference device. Default: cuda")
    parser.add_argument("--compute-type", default="float16", help="faster-whisper compute_type. Default: float16")
    parser.add_argument("--language", default=None, help="Language code, e.g. en/bg. Omit for auto-detect")
    parser.add_argument("--task", default="transcribe", choices=["transcribe", "translate"], help="Whisper task. Default: transcribe")
    parser.add_argument("--vad-filter", default="true", choices=["true", "false"], help="Use VAD filter. Default: true")
    parser.add_argument("--word-timestamps", default="true", choices=["true", "false"], help="Emit word timestamps. Default: true")
    parser.add_argument("--beam-size", type=int, default=5, help="Beam size. Default: 5")
    parser.add_argument("--condition-on-previous-text", default="false", choices=["true", "false"], help="Whisper condition_on_previous_text. Default: false for short reels")
    parser.add_argument("--initial-prompt", default=None, help="Optional initial prompt/context for Whisper")

    # Caption/subtitle chunking contract.
    parser.add_argument("--caption-mode", choices=["auto", "word", "segment"], default="auto", help="How to create subtitle_candidates. Default: auto")
    parser.add_argument("--max-caption-chars", type=int, default=42, help="Preferred max characters per caption chunk. Default: 42")
    parser.add_argument("--max-words-per-caption", type=int, default=9, help="Preferred max words per caption chunk. Default: 9")
    parser.add_argument("--max-caption-duration", type=float, default=3.0, help="Preferred max caption duration in seconds. Default: 3.0")
    parser.add_argument("--min-caption-duration", type=float, default=0.35, help="Preferred min caption duration in seconds. Default: 0.35")

    args, unknown = parser.parse_known_args(argv[1:])
    if unknown:
        # Keep backward compatibility: unknowns are not fatal, but show them in diagnostics.
        args.unknown_args = unknown
    else:
        args.unknown_args = []

    # Backward-compatible positional modes:
    #   transcribe.py input medium
    #   transcribe.py input output.json medium
    #   transcribe.py input output.json medium cuda float16
    positional = list(args.positional or [])
    if positional:
        if positional[0].lower().endswith(".json"):
            if not args.output:
                args.output = positional[0]
            if len(positional) >= 2:
                args.model = positional[1]
            if len(positional) >= 3:
                args.device = positional[2]
            if len(positional) >= 4:
                args.compute_type = positional[3]
        else:
            args.model = positional[0]
            if len(positional) >= 2:
                args.device = positional[1]
            if len(positional) >= 3:
                args.compute_type = positional[2]

    args.input_path = Path(args.input)
    args.output_path = Path(args.output) if args.output else None
    args.vad_filter_bool = str_to_bool(args.vad_filter, True)
    args.word_timestamps_bool = str_to_bool(args.word_timestamps, True)
    args.condition_on_previous_text_bool = str_to_bool(args.condition_on_previous_text, False)

    return args


# -------------------------
# Text / caption helpers
# -------------------------


def clean_spaces(text: Any) -> str:
    text = str(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_word(word: Any) -> str:
    return clean_spaces(str(word or "")).strip()


def roundf(value: Any, digits: int = 3, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return round(float(value), digits)
    except Exception:
        return default


def get_avg_probability(words: List[Dict[str, Any]]) -> Optional[float]:
    probs = [w.get("probability") for w in words if isinstance(w.get("probability"), (int, float))]
    if not probs:
        return None
    return round(float(sum(probs) / len(probs)), 4)


def word_text(words: List[Dict[str, Any]]) -> str:
    text = " ".join([str(w.get("word") or w.get("text") or "").strip() for w in words]).strip()
    # Clean common Whisper spacing around punctuation.
    text = re.sub(r"\s+([,.!?;:%])", r"\1", text)
    text = re.sub(r"([\(\[\{])\s+", r"\1", text)
    text = re.sub(r"\s+([\)\]\}])", r"\1", text)
    return clean_spaces(text)


def make_subtitle_candidate(
    index: int,
    text: str,
    start: Optional[float],
    end: Optional[float],
    source: str,
    words: Optional[List[Dict[str, Any]]] = None,
    segment_ids: Optional[List[int]] = None,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    start = roundf(start, 3, 0.0)
    end = roundf(end, 3, start)
    if end is None or start is None:
        duration = None
    else:
        duration = round(max(0.0, end - start), 3)

    words = words or []
    return {
        "id": f"sub_{index:04d}",
        "index": index,
        "start": start,
        "end": end,
        "duration": duration,
        "text": clean_spaces(text),
        "language": language,
        "source": source,
        "segment_ids": segment_ids or [],
        "word_indices": [w.get("word_index") for w in words if w.get("word_index") is not None],
        "words": words,
        "words_count": len(words),
        "avg_word_probability": get_avg_probability(words),
        "caption_ready": bool(clean_spaces(text)) and start is not None and end is not None and end > start,
    }


def should_flush_caption_chunk(
    current_words: List[Dict[str, Any]],
    max_chars: int,
    max_words: int,
    max_duration: float,
    min_duration: float,
) -> bool:
    if not current_words:
        return False

    start = current_words[0].get("start")
    end = current_words[-1].get("end")
    duration = 0.0
    if isinstance(start, (int, float)) and isinstance(end, (int, float)):
        duration = max(0.0, float(end) - float(start))

    text = word_text(current_words)
    last_word = clean_word(current_words[-1].get("word"))
    ends_sentence = bool(re.search(r"[.!?]$", last_word))

    if len(current_words) >= max_words:
        return True
    if len(text) >= max_chars:
        return True
    if duration >= max_duration:
        return True
    if ends_sentence and duration >= min_duration and len(current_words) >= 3:
        return True

    return False


def build_word_caption_candidates(
    segments: List[Dict[str, Any]],
    language: Optional[str],
    max_chars: int,
    max_words: int,
    max_duration: float,
    min_duration: float,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    candidate_index = 1

    for seg in segments:
        words = seg.get("words") or []
        timed_words = [w for w in words if isinstance(w.get("start"), (int, float)) and isinstance(w.get("end"), (int, float))]
        if not timed_words:
            continue

        current: List[Dict[str, Any]] = []
        for w in timed_words:
            current.append(w)
            if should_flush_caption_chunk(current, max_chars, max_words, max_duration, min_duration):
                text = word_text(current)
                if text:
                    candidates.append(make_subtitle_candidate(
                        index=candidate_index,
                        text=text,
                        start=current[0].get("start"),
                        end=current[-1].get("end"),
                        source="word_timestamps",
                        words=list(current),
                        segment_ids=[seg.get("id")],
                        language=language,
                    ))
                    candidate_index += 1
                current = []

        if current:
            text = word_text(current)
            if text:
                candidates.append(make_subtitle_candidate(
                    index=candidate_index,
                    text=text,
                    start=current[0].get("start"),
                    end=current[-1].get("end"),
                    source="word_timestamps",
                    words=list(current),
                    segment_ids=[seg.get("id")],
                    language=language,
                ))
                candidate_index += 1

    return candidates


def build_segment_caption_candidates(
    segments: List[Dict[str, Any]],
    language: Optional[str],
    start_index: int = 1,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    idx = start_index
    for seg in segments:
        text = clean_spaces(seg.get("text"))
        if not text:
            continue
        candidates.append(make_subtitle_candidate(
            index=idx,
            text=text,
            start=seg.get("start"),
            end=seg.get("end"),
            source="segments",
            words=seg.get("words") or [],
            segment_ids=[seg.get("id")],
            language=language,
        ))
        idx += 1
    return candidates


def attach_candidate_ids_to_segments(segments: List[Dict[str, Any]], candidates: List[Dict[str, Any]]) -> None:
    by_segment: Dict[int, List[str]] = {}
    for cand in candidates:
        for sid in cand.get("segment_ids") or []:
            if sid is None:
                continue
            by_segment.setdefault(int(sid), []).append(cand.get("id"))

    for seg in segments:
        sid = seg.get("id")
        seg["subtitle_candidate_ids"] = by_segment.get(int(sid), []) if sid is not None else []


# -------------------------
# Transcription normalization
# -------------------------


def normalize_transcription_segments(raw_segments: Iterable[Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    result_segments: List[Dict[str, Any]] = []
    all_words: List[Dict[str, Any]] = []
    word_index = 1

    for segment_index, segment in enumerate(raw_segments, start=1):
        segment_words: List[Dict[str, Any]] = []

        raw_words = getattr(segment, "words", None) or []
        for word in raw_words:
            word_obj = {
                "word_index": word_index,
                "segment_id": segment_index,
                "word": clean_word(getattr(word, "word", "")),
                "start": roundf(getattr(word, "start", None), 3, None),
                "end": roundf(getattr(word, "end", None), 3, None),
                "duration": None,
                "probability": roundf(getattr(word, "probability", None), 4, None),
            }
            if isinstance(word_obj["start"], (int, float)) and isinstance(word_obj["end"], (int, float)):
                word_obj["duration"] = round(max(0.0, float(word_obj["end"]) - float(word_obj["start"])), 3)
            segment_words.append(word_obj)
            all_words.append(word_obj)
            word_index += 1

        start = roundf(getattr(segment, "start", None), 3, 0.0)
        end = roundf(getattr(segment, "end", None), 3, start)
        text = clean_spaces(getattr(segment, "text", ""))
        seg_obj: Dict[str, Any] = {
            "id": segment_index,
            "start": start,
            "end": end,
            "duration": round(max(0.0, float(end or 0.0) - float(start or 0.0)), 3) if start is not None and end is not None else None,
            "text": text,
            "words": segment_words,
            "words_count": len(segment_words),
            "avg_word_probability": get_avg_probability(segment_words),
        }

        # faster-whisper Segment metadata is useful for QA, but not guaranteed.
        for attr in ("avg_logprob", "no_speech_prob", "compression_ratio", "seek"):
            try:
                value = getattr(segment, attr, None)
                if value is not None:
                    seg_obj[attr] = roundf(value, 4, value)
            except Exception:
                pass

        result_segments.append(seg_obj)

    return result_segments, all_words


def build_empty_output(args: argparse.Namespace, runtime_sec: float, reason: str = "no_speech_detected") -> Dict[str, Any]:
    return {
        "success": True,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "speech_detected": False,
        "reason": reason,
        "language": None,
        "language_probability": None,
        "duration": None,
        "model": args.model,
        "device": args.device,
        "compute_type": args.compute_type,
        "input_path": str(args.input_path),
        "output_path": str(args.output_path) if args.output_path else None,
        "runtime_sec": round(runtime_sec, 4),
        "segments": [],
        "words": [],
        "subtitle_candidates": [],
        "subtitle_clips": [],
        "text": "",
        "summary": {
            "segments_count": 0,
            "words_count": 0,
            "subtitle_candidates_count": 0,
            "speech_detected": False,
            "word_timestamps_available": False,
            "caption_ready": False,
        },
        "transcribe_options": transcribe_options_dict(args),
        "diagnostics": {
            "python_executable": sys.executable,
            "sys_prefix": sys.prefix,
            "cuda_dlls": cuda_diagnostics(),
        },
    }


def transcribe_options_dict(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "language": args.language,
        "task": args.task,
        "vad_filter": args.vad_filter_bool,
        "word_timestamps": args.word_timestamps_bool,
        "beam_size": args.beam_size,
        "condition_on_previous_text": args.condition_on_previous_text_bool,
        "initial_prompt_provided": bool(args.initial_prompt),
        "caption_mode": args.caption_mode,
        "max_caption_chars": args.max_caption_chars,
        "max_words_per_caption": args.max_words_per_caption,
        "max_caption_duration": args.max_caption_duration,
        "min_caption_duration": args.min_caption_duration,
    }


# -------------------------
# Main
# -------------------------


def main() -> None:
    started = time.monotonic()
    args = parse_args(sys.argv)

    if not args.input_path.exists():
        fail("File not found", {
            "input_path": str(args.input_path),
            "cwd": os.getcwd(),
        })

    try:
        # Import AFTER DLL directories are registered.
        from faster_whisper import WhisperModel

        cublas_path = dll_exists("cublas64_12.dll")
        if args.device.lower() == "cuda" and not cublas_path:
            fail("cublas64_12.dll was not found in the current Python environment NVIDIA package folders.", {
                "python_executable": sys.executable,
                "sys_prefix": sys.prefix,
                "site_package_roots": [str(p) for p in get_site_package_roots()],
                "checked_dll_dirs": [str(p) for p in CUDA_DLL_DIRS],
                "existing_dll_dirs": EXISTING_DLL_DIRS,
                "dll_add_errors": DLL_ADD_ERRORS,
                "hint": "Install nvidia-cublas-cu12 inside the same venv used by this command, or set VIDEO_CLONER_AUDIO_SITE_PACKAGES.",
            })

        model = WhisperModel(
            args.model,
            device=args.device,
            compute_type=args.compute_type,
        )

        transcribe_kwargs: Dict[str, Any] = {
            "language": args.language,
            "task": args.task,
            "vad_filter": args.vad_filter_bool,
            "word_timestamps": args.word_timestamps_bool,
            "beam_size": args.beam_size,
            "condition_on_previous_text": args.condition_on_previous_text_bool,
        }
        if args.initial_prompt:
            transcribe_kwargs["initial_prompt"] = args.initial_prompt

        raw_segments, info = model.transcribe(str(args.input_path), **transcribe_kwargs)
        segments, words = normalize_transcription_segments(raw_segments)

        language = getattr(info, "language", None)
        language_probability = roundf(getattr(info, "language_probability", None), 4, None)
        duration = roundf(getattr(info, "duration", None), 3, None)

        if args.caption_mode == "segment":
            subtitle_candidates = build_segment_caption_candidates(segments, language)
        else:
            subtitle_candidates = build_word_caption_candidates(
                segments=segments,
                language=language,
                max_chars=max(12, int(args.max_caption_chars)),
                max_words=max(1, int(args.max_words_per_caption)),
                max_duration=max(0.5, float(args.max_caption_duration)),
                min_duration=max(0.1, float(args.min_caption_duration)),
            )
            if args.caption_mode == "auto" and not subtitle_candidates:
                subtitle_candidates = build_segment_caption_candidates(segments, language)

        attach_candidate_ids_to_segments(segments, subtitle_candidates)

        full_text = clean_spaces(" ".join([s.get("text", "") for s in segments]))
        low_confidence_words = [w for w in words if isinstance(w.get("probability"), (int, float)) and float(w["probability"]) < 0.5]
        timed_words_count = len([w for w in words if isinstance(w.get("start"), (int, float)) and isinstance(w.get("end"), (int, float))])
        speech_detected = bool(full_text or segments)

        output: Dict[str, Any] = {
            "success": True,
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "version": VERSION,
            "speech_detected": speech_detected,
            "language": language,
            "language_probability": language_probability,
            "duration": duration,
            "model": args.model,
            "device": args.device,
            "compute_type": args.compute_type,
            "input_path": str(args.input_path),
            "output_path": str(args.output_path) if args.output_path else None,
            "runtime_sec": round(time.monotonic() - started, 4),
            "transcribe_options": transcribe_options_dict(args),
            "summary": {
                "segments_count": len(segments),
                "words_count": len(words),
                "timed_words_count": timed_words_count,
                "subtitle_candidates_count": len(subtitle_candidates),
                "speech_detected": speech_detected,
                "word_timestamps_available": timed_words_count > 0,
                "caption_ready": len(subtitle_candidates) > 0,
                "avg_word_probability": get_avg_probability(words),
                "low_confidence_words_count": len(low_confidence_words),
                "text_chars": len(full_text),
            },
            "captioning": {
                "subtitle_candidates_source": "word_timestamps" if subtitle_candidates and subtitle_candidates[0].get("source") == "word_timestamps" else "segments",
                "recommended_style_source": "detect_caption_style.py",
                "recommended_placement": "bottom_center",
                "recommended_max_lines": 2,
                "compiler_target": "generic_edit_commands.subtitle_clips",
            },
            "segments": segments,
            "words": words,
            "subtitle_candidates": subtitle_candidates,
            # Alias for downstream tools that already think in editor clips.
            "subtitle_clips": subtitle_candidates,
            "text": full_text,
            "diagnostics": {
                "python_executable": sys.executable,
                "sys_prefix": sys.prefix,
                "site_package_roots": [str(p) for p in get_site_package_roots()],
                "cuda_dlls": cuda_diagnostics(),
                "unknown_args": getattr(args, "unknown_args", []),
            },
        }

        if not speech_detected:
            output.update(build_empty_output(args, time.monotonic() - started))

        if args.output_path:
            args.output_path.parent.mkdir(parents=True, exist_ok=True)
            args.output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
            output["file_saved"] = True

        print_json(output)
        sys.exit(0)

    except Exception as exc:
        print_json({
            "success": False,
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "version": VERSION,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "traceback": traceback.format_exc(),
            "input_path": str(args.input_path),
            "output_path": str(args.output_path) if args.output_path else None,
            "runtime_sec": round(time.monotonic() - started, 4),
            "python_executable": sys.executable,
            "sys_prefix": sys.prefix,
            "site_package_roots": [str(p) for p in get_site_package_roots()],
            "checked_dll_dirs": [str(p) for p in CUDA_DLL_DIRS],
            "existing_dll_dirs": EXISTING_DLL_DIRS,
            "dll_add_errors": DLL_ADD_ERRORS,
            "found_dlls": {
                "cublas64_12.dll": dll_exists("cublas64_12.dll"),
                "cudnn_ops64_9.dll": dll_exists("cudnn_ops64_9.dll"),
                "cudnn64_9.dll": dll_exists("cudnn64_9.dll"),
                "cudart64_12.dll": dll_exists("cudart64_12.dll"),
                "cublas_matches": find_any_dll_contains("cublas"),
                "cudnn_matches": find_any_dll_contains("cudnn"),
            },
            "hint": "If DLLs are found but still cannot load, install matching CUDA Toolkit 12.x system-wide or try --compute-type int8_float16.",
        })
        sys.exit(1)


if __name__ == "__main__":
    main()
