#!/usr/bin/env python3
"""Generate compiler-safe caption lifecycle authority from dense source evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Callable, Mapping, Sequence

from scripts.davinci import caption_lifecycle_authority_step_3D as composer
from scripts.davinci import compile_davinci_textplus_fcpxml as canonical
from scripts.davinci import redetect_caption_lifecycle_step_3D as dense
from scripts.standalone.video_cloner_textplus import prepare_textplus_authority


class LifecycleGenerationError(RuntimeError):
    pass


def _semantic(value: object) -> str:
    return canonical.normalize_semantic_caption_text(value)


def _cue_id(value: object) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return f"sub_{int(digits):03d}" if digits and int(digits) > 0 else ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _style_events(style_data: Mapping[str, object]) -> list[dict]:
    for key in ("caption_style_events", "style_events"):
        rows = style_data.get(key)
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, Mapping)]
    return []


def _seed_events(cue: Mapping[str, object], events: Sequence[Mapping[str, object]]) -> tuple[list[dict], str | None]:
    source_ids = {_cue_id(value) for value in cue.get("source_cue_ids", [cue.get("id")])}
    associated = [event for event in events if _cue_id(event.get("cue_id")) in source_ids]
    expected = _semantic(cue.get("text"))
    eligible: list[dict] = []
    for event in associated:
        observed = event.get("observed_texts")
        observations = event.get("observations")
        selected = _semantic(event.get("observed_text"))
        if not isinstance(observed, list) or len(observed) < 2 or not isinstance(observations, list):
            continue
        semantics = [_semantic(value) for value in observed]
        usable = [row for row in observations if isinstance(row, Mapping) and _semantic(row.get("text")) == expected]
        if expected and selected == expected and all(value == expected for value in semantics) and len(usable) >= 2:
            eligible.append({**dict(event), "observations": [dict(row) for row in usable]})
    if len(eligible) == 1:
        return eligible, None
    if len(eligible) > 1:
        return [], "ambiguous_source_association"
    if associated:
        return [], "contaminated_or_insufficient_ocr_seed"
    return [], None


def _pixel_bbox(value: object, width: int, height: int) -> tuple[int, int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        box = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in box):
        return None
    if max(box) <= 1.0:
        box = [box[0] * width, box[1] * height, box[2] * width, box[3] * height]
    x1, y1, x2, y2 = box
    x1 = max(0, min(width - 1, int(math.floor(x1))))
    y1 = max(0, min(height - 1, int(math.floor(y1))))
    x2 = max(x1 + 1, min(width, int(math.ceil(x2))))
    y2 = max(y1 + 1, min(height, int(math.ceil(y2))))
    return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None


def _dense_track(
    capture: object,
    frame_count: int,
    width: int,
    height: int,
    source_fps: float,
    timeline_fps: float,
    cue: Mapping[str, object],
    event: Mapping[str, object],
    search_padding_seconds: float,
) -> dict:
    observations = list(event["observations"])
    seed = max(
        observations,
        key=lambda row: (
            float(row.get("caption_score") or 0.0),
            float(row.get("transcript_match_score") or 0.0),
            -float(row.get("timestamp") or 0.0),
        ),
    )
    bbox = _pixel_bbox(seed.get("bbox") or seed.get("normalized_bbox"), width, height)
    timestamp = float(seed.get("timestamp"))
    if bbox is None or not math.isfinite(timestamp):
        raise LifecycleGenerationError("invalid_direct_ocr_seed")
    seed_frame = max(0, min(frame_count - 1, int(round(timestamp * source_fps))))
    seed_image = dense.read_frame(capture, seed_frame)
    x1, y1, x2, y2 = bbox
    template = seed_image[y1:y2, x1:x2]
    if template.size == 0 or min(template.shape[:2]) < 8:
        raise LifecycleGenerationError("invalid_direct_ocr_template")

    transcript_start = int(cue["start_frame"])
    transcript_end = int(cue["end_frame"])
    padding = max(0.0, float(search_padding_seconds))
    search_start = max(0, int(math.floor((transcript_start / timeline_fps - padding) * source_fps)))
    search_end = min(frame_count - 1, int(math.ceil((transcript_end / timeline_fps + padding) * source_fps)))
    search_bbox = dense.expand_bbox(bbox, width, height)
    sx1, sy1, sx2, sy2 = search_bbox
    frame_indices: list[int] = []
    scores: list[float] = []
    for frame_index in range(search_start, search_end + 1):
        frame = dense.read_frame(capture, frame_index)
        match = dense.multi_scale_match(frame[sy1:sy2, sx1:sx2], template)
        frame_indices.append(frame_index)
        scores.append(float(match["score"]))

    segment = dense.segment_around_seed(frame_indices, scores, seed_frame)
    left, right = [int(value) for value in segment["segment_indices"]]
    smoothed = [float(value) for value in segment["smoothed_scores"]]
    weak = float(segment["weak_threshold"])
    left_proven = (left > 0 and smoothed[left - 1] < weak) or (left == 0 and search_start == 0)
    right_proven = (right + 1 < len(smoothed) and smoothed[right + 1] < weak) or (
        right + 1 == len(smoothed) and search_end == frame_count - 1
    )
    if not left_proven or not right_proven:
        raise LifecycleGenerationError("visual_segment_boundary_unproven")
    if not (frame_indices[left] <= seed_frame <= frame_indices[right]):
        raise LifecycleGenerationError("direct_ocr_seed_outside_dense_segment")

    first = frame_indices[left]
    last = frame_indices[right]
    lifecycle = [
        int(round(first / source_fps * timeline_fps)),
        int(round((last + 1) / source_fps * timeline_fps)),
    ]
    if lifecycle[1] <= lifecycle[0]:
        raise LifecycleGenerationError("invalid_half_open_lifecycle")
    return {
        "cue_id": cue["id"],
        "text": cue["text"],
        "accepted_source_instance": True,
        "source_exactness": "source_video_dense_template_track",
        "confidence": {
            "label": "high" if float(segment["peak_score"]) >= 0.62 else "medium",
            "dense_observation_count": int(segment["segment_frame_count"]),
        },
        "geometry": {"first_visible_frame": lifecycle[0], "last_visible_frame": lifecycle[1] - 1},
        "frame_observations": [],
        "boundary_evidence": {
            "left_proven": left_proven,
            "right_proven": right_proven,
            "first_visible_source_frame": first,
            "last_visible_source_frame": last,
            "search_start_source_frame": search_start,
            "search_end_source_frame": search_end,
        },
    }


def generate_lifecycle(
    authority_cues: Sequence[Mapping[str, object]],
    style_data: Mapping[str, object],
    source_video: str | Path,
    timeline_fps: float,
    *,
    search_padding_seconds: float = 0.75,
    tracker: Callable[..., dict] = _dense_track,
) -> dict:
    if not authority_cues or timeline_fps <= 0:
        raise LifecycleGenerationError("authority cues and positive timeline fps are required")
    cue_ids = [str(cue.get("id") or "") for cue in authority_cues]
    if any(not cue_id for cue_id in cue_ids) or len(set(cue_ids)) != len(cue_ids):
        raise LifecycleGenerationError("authority cue IDs are empty or duplicated")

    video_path = Path(source_video).expanduser().resolve()
    capture = dense.cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise LifecycleGenerationError(f"source video could not be opened: {video_path}")
    source_fps = float(capture.get(dense.cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(capture.get(dense.cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(capture.get(dense.cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(dense.cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if source_fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
        capture.release()
        raise LifecycleGenerationError("source video metadata is invalid")

    events = _style_events(style_data)
    tracks: list[dict] = []
    diagnostics: list[dict] = []
    try:
        for cue in authority_cues:
            candidates, reason = _seed_events(cue, events)
            if reason:
                diagnostics.append({"cue_id": cue["id"], "state": "needs_redetection", "reason": reason})
                continue
            if not candidates:
                continue
            try:
                track = tracker(
                    capture, frame_count, width, height, source_fps, timeline_fps,
                    cue, candidates[0], search_padding_seconds,
                )
                boundary = track.get("boundary_evidence") if isinstance(track, Mapping) else None
                geometry = track.get("geometry") if isinstance(track, Mapping) else None
                if (
                    track.get("accepted_source_instance") is not True
                    or not isinstance(boundary, Mapping)
                    or boundary.get("left_proven") is not True
                    or boundary.get("right_proven") is not True
                    or not isinstance(geometry, Mapping)
                    or int(geometry.get("last_visible_frame", -1)) < int(geometry.get("first_visible_frame", 0))
                ):
                    raise LifecycleGenerationError("dense_track_acceptance_contract_failed")
                tracks.append(dict(track))
            except Exception as error:
                diagnostics.append({
                    "cue_id": cue["id"],
                    "state": "needs_redetection",
                    "reason": str(error),
                })
    finally:
        capture.release()

    items = [
        {
            "cue_id": cue["id"],
            "cue_index": index,
            "name": f"VC_TEXTPLUS_{index:04d}_{cue['id']}",
            "text": cue["text"],
            "start_frame": int(cue["start_frame"]),
            "end_frame": int(cue["end_frame"]),
            "selected": False,
            "animation": None,
        }
        for index, cue in enumerate(authority_cues, start=1)
    ]
    result = composer.build_plan({"tracks": tracks}, {"items": items})
    diagnostic_ids = {row["cue_id"] for row in diagnostics}
    for layer in result["layers"]:
        if layer["cue_id"] in diagnostic_ids and layer["timing_authority"] == "transcript_fallback":
            layer["lifecycle_status"] = "transcript_fallback_needs_redetection"
    result["mandatory_visual_redetection_queue"] = []
    result["diagnostics"] = diagnostics
    result["summary"]["needs_redetection_count"] = len(diagnostics)
    result["summary"]["needs_redetection_cue_ids"] = [row["cue_id"] for row in diagnostics]
    result["source_video"] = {
        "path": str(video_path),
        "sha256": _sha256(video_path),
        "fps": source_fps,
        "frame_count": frame_count,
        "width": width,
        "height": height,
    }
    result.pop("plan_semantic_sha256", None)
    result["plan_semantic_sha256"] = composer.canonical_hash(result)
    return result


def generate_from_files(
    generic_path: str | Path,
    caption_style_path: str | Path,
    source_video: str | Path,
    output_path: str | Path,
    *,
    search_padding_seconds: float = 0.75,
) -> dict:
    generic = json.loads(Path(generic_path).read_text(encoding="utf-8-sig"))
    style = json.loads(Path(caption_style_path).read_text(encoding="utf-8-sig"))
    prepared = prepare_textplus_authority(generic, style)
    result = generate_lifecycle(
        prepared["cues"], style, source_video, float(prepared["fps"]),
        search_padding_seconds=search_padding_seconds,
    )
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate generic dense caption lifecycle authority without Resolve.")
    parser.add_argument("--generic", required=True)
    parser.add_argument("--caption-style", required=True)
    parser.add_argument("--source-video", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--search-padding-seconds", type=float, default=0.75)
    args = parser.parse_args()
    try:
        result = generate_from_files(
            args.generic, args.caption_style, args.source_video, args.output,
            search_padding_seconds=args.search_padding_seconds,
        )
    except Exception as error:
        print(json.dumps({"ok": False, "error": f"{type(error).__name__}: {error}"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": result["ok"], "summary": result["summary"], "output": str(Path(args.output).resolve())}, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
