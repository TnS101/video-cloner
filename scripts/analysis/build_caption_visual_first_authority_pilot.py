#!/usr/bin/env python3
"""Build a visual-first caption-authority pilot for seven rejected caption windows.

The source video and source-derived OCR/tracking artifacts are primary. Transcript
cues are used only to seed broad search windows and to attach canonical word
aliases. The script never promotes transcript timestamps to visual lifecycle
authority.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import cv2  # type: ignore
import numpy as np

TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_AUTHORITY_PILOT_V1"
SCHEMA = "video_cloner_caption_visual_first_authority_pilot"
SCHEMA_VERSION = 1
TIMELINE_FPS = 24.0

CONTRACT_RELATIVE = Path(
    "data/DZsqH7auhjt/analysis/"
    "DZsqH7auhjt_caption_visual_first_pilot_contract.json"
)
LIFECYCLE_RELATIVE = Path(
    "data/DZsqH7auhjt/analysis/"
    "DZsqH7auhjt_caption_lifecycle_authority_step_3D_calibrated.json"
)
TRACKS_RELATIVE = Path(
    "data/DZsqH7auhjt/analysis/"
    "DZsqH7auhjt_caption_word_instance_tracks_step_3B_6B.json"
)
STYLE_RELATIVE = Path(
    "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_style.json"
)
SRT_RELATIVE = Path(
    "data/DZsqH7auhjt/davinci/DZsqH7auhjt_word_subtitles.srt"
)
VIDEO_CANDIDATES = (
    Path("input/DZsqH7auhjt.mp4"),
    Path("media/DZsqH7auhjt_proxy.mp4"),
)


class VisualAuthorityError(RuntimeError):
    pass


@dataclass(frozen=True)
class Cue:
    cue_id: str
    index: int
    start_seconds: float
    end_seconds: float
    text: str

    @property
    def transcript_window(self) -> list[int]:
        return [
            int(round(self.start_seconds * TIMELINE_FPS)),
            int(round(self.end_seconds * TIMELINE_FPS)),
        ]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_cue_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and float(value).is_integer():
        index = int(value)
        return f"sub_{index:03d}" if index > 0 else None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"sub[_-]?(\d+)", text, flags=re.IGNORECASE)
    if match:
        index = int(match.group(1))
        return f"sub_{index:03d}" if index > 0 else None
    if text.isdigit():
        index = int(text)
        return f"sub_{index:03d}" if index > 0 else None
    return None


def normalize_text(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def text_similarity(left: Any, right: Any) -> float:
    left_normalized = normalize_text(left)
    right_normalized = normalize_text(right)
    if not left_normalized or not right_normalized:
        return 0.0
    if left_normalized == right_normalized:
        return 1.0
    if left_normalized in right_normalized or right_normalized in left_normalized:
        shorter = min(len(left_normalized), len(right_normalized))
        longer = max(len(left_normalized), len(right_normalized))
        return 0.72 + 0.28 * (shorter / longer)
    return difflib.SequenceMatcher(None, left_normalized, right_normalized).ratio()


def parse_timestamp(value: str) -> float:
    hours, minutes, rest = value.strip().split(":")
    seconds, milliseconds = rest.split(",")
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(milliseconds) / 1000.0
    )


def parse_srt(path: Path) -> list[Cue]:
    text = path.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\s*\n", text.strip())
    cues: list[Cue] = []
    for block in blocks:
        lines = [line.rstrip("\r") for line in block.splitlines()]
        if len(lines) < 3:
            continue
        try:
            index = int(lines[0].strip())
        except ValueError as exc:
            raise VisualAuthorityError(f"invalid_srt_index:{lines[0]!r}") from exc
        if "-->" not in lines[1]:
            raise VisualAuthorityError(f"invalid_srt_time:{lines[1]!r}")
        start_text, end_text = [part.strip() for part in lines[1].split("-->", 1)]
        cues.append(
            Cue(
                cue_id=f"sub_{index:03d}",
                index=index,
                start_seconds=parse_timestamp(start_text),
                end_seconds=parse_timestamp(end_text),
                text=" ".join(lines[2:]).strip(),
            )
        )
    if len(cues) != 116:
        raise VisualAuthorityError(f"unexpected_srt_cue_count:{len(cues)}")
    return cues


def unique_index(
    rows: Iterable[dict[str, Any]],
    key: str,
    label: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = normalize_cue_id(row.get(key)) if key == "cue_id" else str(row.get(key) or "").strip()
        if not value:
            continue
        if value in result:
            raise VisualAuthorityError(f"duplicate_{label}:{value}")
        result[value] = row
    return result


def finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def confidence_score(event: dict[str, Any]) -> float:
    confidence = event.get("confidence")
    if isinstance(confidence, dict):
        score = finite_float(confidence.get("score"))
        if score is not None:
            return max(0.0, min(1.0, score))
    score = finite_float(confidence)
    return max(0.0, min(1.0, score or 0.0))


def style_event_window(event: dict[str, Any]) -> list[int] | None:
    start = finite_float(event.get("start"))
    end = finite_float(event.get("end"))
    if start is None or end is None or end <= start:
        return None
    return [
        int(math.floor(start * TIMELINE_FPS)),
        int(math.ceil(end * TIMELINE_FPS)),
    ]


def style_event_bbox(event: dict[str, Any]) -> list[float] | None:
    placement = event.get("placement")
    if not isinstance(placement, dict):
        return None
    bbox = placement.get("normalized_bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    values = [finite_float(value) for value in bbox]
    if any(value is None for value in values):
        return None
    x1, y1, x2, y2 = [float(value) for value in values]
    if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
        return None
    return [x1, y1, x2, y2]


def track_observations(track: dict[str, Any]) -> list[dict[str, Any]]:
    observations = track.get("frame_observations")
    if not isinstance(observations, list):
        return []
    result: list[dict[str, Any]] = []
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        timeline_frame = finite_float(observation.get("timeline_frame"))
        bbox = observation.get("normalized_bbox")
        if timeline_frame is None or not isinstance(bbox, list) or len(bbox) != 4:
            continue
        bbox_values = [finite_float(value) for value in bbox]
        if any(value is None for value in bbox_values):
            continue
        x1, y1, x2, y2 = [float(value) for value in bbox_values]
        if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
            continue
        row = dict(observation)
        row["timeline_frame"] = int(round(timeline_frame))
        row["normalized_bbox"] = [x1, y1, x2, y2]
        result.append(row)
    result.sort(key=lambda row: int(row["timeline_frame"]))
    return result


def simplify_numeric_path(
    observations: Sequence[dict[str, Any]],
    value_key: str,
    max_points: int = 7,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for observation in observations:
        value = observation.get(value_key)
        if isinstance(value, list):
            numbers = [finite_float(item) for item in value]
            if any(number is None for number in numbers):
                continue
            normalized_value: Any = [round(float(number), 8) for number in numbers]
        else:
            number = finite_float(value)
            if number is None:
                continue
            normalized_value = round(float(number), 8)
        rows.append(
            {
                "timeline_frame": int(observation["timeline_frame"]),
                "value": normalized_value,
            }
        )
    if len(rows) <= max_points:
        return rows
    selected_indices = sorted(
        {
            int(round(index * (len(rows) - 1) / (max_points - 1)))
            for index in range(max_points)
        }
    )
    return [rows[index] for index in selected_indices]


def candidate_event_score(
    event: dict[str, Any],
    token: dict[str, Any],
    cue_ids: set[str],
    context_window: list[int],
) -> float:
    event_window = style_event_window(event)
    if event_window is None:
        return -1.0
    if event_window[1] < context_window[0] or event_window[0] > context_window[1]:
        return -1.0

    score = confidence_score(event) * 0.25
    event_cue = normalize_cue_id(event.get("cue_id"))
    if event_cue and event_cue in cue_ids:
        score += 1.0

    aliases = [token.get("display_text")] + list(token.get("transcript_aliases") or [])
    observed_values = [event.get("text"), event.get("observed_text")]
    observed_texts = event.get("observed_texts")
    if isinstance(observed_texts, list):
        observed_values.extend(observed_texts)
    similarity = max(
        (
            text_similarity(alias, observed)
            for alias in aliases
            for observed in observed_values
            if alias and observed
        ),
        default=0.0,
    )
    score += similarity * 0.85
    return score


def choose_style_events(
    style_events: Sequence[dict[str, Any]],
    token: dict[str, Any],
    context_window: list[int],
) -> list[dict[str, Any]]:
    cue_ids = {
        cue_id
        for cue_id in (
            normalize_cue_id(value)
            for value in token.get("transcript_cue_ids") or []
        )
        if cue_id
    }
    scored: list[tuple[float, dict[str, Any]]] = []
    for event in style_events:
        score = candidate_event_score(event, token, cue_ids, context_window)
        if score >= 0.55:
            scored.append((score, event))
    scored.sort(
        key=lambda pair: (
            pair[0],
            confidence_score(pair[1]),
            -(style_event_window(pair[1]) or [0, 0])[0],
        ),
        reverse=True,
    )
    return [event for _, event in scored[:4]]


def visual_windows_from_evidence(
    events: Sequence[dict[str, Any]],
    tracks: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for event in events:
        window = style_event_window(event)
        if window:
            windows.append(
                {
                    "source": "style_event",
                    "source_id": event.get("event_id"),
                    "window": window,
                    "confidence": round(confidence_score(event), 6),
                }
            )
    for track in tracks:
        observations = track_observations(track)
        if observations:
            windows.append(
                {
                    "source": "source_track_observations",
                    "source_id": normalize_cue_id(track.get("cue_id")),
                    "window": [
                        int(observations[0]["timeline_frame"]),
                        int(observations[-1]["timeline_frame"]) + 1,
                    ],
                    "confidence": round(
                        finite_float((track.get("confidence") or {}).get("median_assignment_score"))
                        or 0.0,
                        6,
                    ),
                }
            )
        else:
            geometry = track.get("geometry")
            if isinstance(geometry, dict):
                first = finite_float(geometry.get("first_visible_frame"))
                last = finite_float(geometry.get("last_visible_frame"))
                if first is not None and last is not None and last >= first:
                    windows.append(
                        {
                            "source": "source_track_geometry",
                            "source_id": normalize_cue_id(track.get("cue_id")),
                            "window": [int(round(first)), int(round(last)) + 1],
                            "confidence": 0.35,
                        }
                    )
    return windows


def union_window(windows: Sequence[dict[str, Any]]) -> list[int] | None:
    valid = [row.get("window") for row in windows]
    valid = [
        row
        for row in valid
        if isinstance(row, list)
        and len(row) == 2
        and int(row[1]) > int(row[0])
    ]
    if not valid:
        return None
    return [min(int(row[0]) for row in valid), max(int(row[1]) for row in valid)]


def style_fingerprint(events: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    if not events:
        return None
    event = max(events, key=confidence_score)
    typography = event.get("typography") if isinstance(event.get("typography"), dict) else {}
    colors = event.get("colors") if isinstance(event.get("colors"), dict) else {}
    stroke = event.get("stroke") if isinstance(event.get("stroke"), dict) else {}
    shadow = event.get("shadow") if isinstance(event.get("shadow"), dict) else {}
    return {
        "style_event_id": event.get("event_id"),
        "style_profile_id": event.get("style_profile_id"),
        "observed_text": event.get("observed_text"),
        "font_family": typography.get("font_family"),
        "font_weight": typography.get("font_weight"),
        "font_style": typography.get("font_style"),
        "font_height_px": typography.get("font_height_px"),
        "font_height_ratio": typography.get("font_height_ratio"),
        "case_style": typography.get("case_style"),
        "fill": colors.get("fill"),
        "stroke_enabled": stroke.get("enabled"),
        "stroke_color": stroke.get("color"),
        "stroke_width_px_estimate": stroke.get("width_px_estimate"),
        "shadow_enabled": shadow.get("enabled"),
        "shadow_color": shadow.get("color"),
        "shadow_opacity_estimate": shadow.get("opacity_estimate"),
        "shadow_blur_px_estimate": shadow.get("blur_px_estimate"),
        "confidence": round(confidence_score(event), 6),
    }


def animation_evidence(events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in events:
        animation = event.get("animation")
        if not isinstance(animation, dict):
            continue
        if not animation.get("detected"):
            continue
        result.append(
            {
                "style_event_id": event.get("event_id"),
                "type": animation.get("type"),
                "style": animation.get("style"),
                "confidence": animation.get("confidence"),
                "metrics": animation.get("metrics"),
                "keyframes": animation.get("keyframes"),
            }
        )
    return result


def best_track_paths(tracks: Sequence[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[tuple[int, dict[str, Any], list[dict[str, Any]]]] = []
    for track in tracks:
        observations = track_observations(track)
        candidates.append((len(observations), track, observations))
    candidates.sort(key=lambda row: row[0], reverse=True)
    if not candidates or candidates[0][0] == 0:
        return {
            "position_path": [],
            "size_path": [],
            "opacity_path": [],
            "source_track_id": None,
        }
    _, track, observations = candidates[0]
    position_observations = [
        {
            "timeline_frame": row["timeline_frame"],
            "position": row.get("position"),
        }
        for row in observations
        if isinstance(row.get("position"), list)
    ]
    return {
        "position_path": simplify_numeric_path(position_observations, "position"),
        "size_path": simplify_numeric_path(observations, "scale_proxy"),
        "opacity_path": simplify_numeric_path(observations, "opacity_proxy"),
        "source_track_id": normalize_cue_id(track.get("cue_id")),
    }


def context_window_from_cues(
    cue_ids: Sequence[str],
    cues: dict[str, Cue],
    padding_frames: int,
) -> list[int]:
    selected = [cues[cue_id] for cue_id in cue_ids if cue_id in cues]
    if not selected:
        raise VisualAuthorityError("group_has_no_valid_search_seed_cues")
    start = min(cue.transcript_window[0] for cue in selected) - padding_frames
    end = max(cue.transcript_window[1] for cue in selected) + padding_frames
    return [max(0, start), max(start + 1, end)]


def nearest_track_bbox(
    tracks: Sequence[dict[str, Any]],
    timeline_frame: int,
    max_distance: int = 4,
) -> list[tuple[list[float], str]]:
    result: list[tuple[list[float], str]] = []
    for track in tracks:
        observations = track_observations(track)
        if not observations:
            continue
        nearest = min(
            observations,
            key=lambda row: abs(int(row["timeline_frame"]) - timeline_frame),
        )
        if abs(int(nearest["timeline_frame"]) - timeline_frame) <= max_distance:
            result.append(
                (
                    [float(value) for value in nearest["normalized_bbox"]],
                    str(track.get("text") or normalize_cue_id(track.get("cue_id")) or "track"),
                )
            )
    return result


def active_style_boxes(
    events: Sequence[dict[str, Any]],
    timeline_frame: int,
    tolerance_frames: int = 3,
) -> list[tuple[list[float], str]]:
    result: list[tuple[list[float], str]] = []
    for event in events:
        window = style_event_window(event)
        bbox = style_event_bbox(event)
        if window is None or bbox is None:
            continue
        if window[0] - tolerance_frames <= timeline_frame < window[1] + tolerance_frames:
            label = str(event.get("observed_text") or event.get("text") or "style")
            result.append((bbox, label))
    return result


def sample_frames_for_group(
    context_window: list[int],
    token_rows: Sequence[dict[str, Any]],
    count: int = 12,
) -> list[int]:
    start, end = context_window
    frames = {
        int(round(start + index * (end - start - 1) / max(1, count - 1)))
        for index in range(count)
    }
    for token in token_rows:
        window = token.get("visual_window")
        if isinstance(window, list) and len(window) == 2 and window[1] > window[0]:
            frames.add(int(window[0]))
            frames.add(int((window[0] + window[1] - 1) // 2))
            frames.add(int(window[1] - 1))
    return sorted(frame for frame in frames if start <= frame < end)


def read_video_frame(
    capture: cv2.VideoCapture,
    source_frame: int,
) -> np.ndarray:
    capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, source_frame))
    ok, frame = capture.read()
    if not ok or frame is None:
        raise VisualAuthorityError(f"video_frame_read_failed:{source_frame}")
    return frame


def timeline_to_source_frame(timeline_frame: int, source_fps: float) -> int:
    return int(round((timeline_frame / TIMELINE_FPS) * source_fps))


def draw_normalized_box(
    image: np.ndarray,
    bbox: Sequence[float],
    label: str,
    color: tuple[int, int, int],
) -> None:
    height, width = image.shape[:2]
    x1 = max(0, min(width - 1, int(round(float(bbox[0]) * width))))
    y1 = max(0, min(height - 1, int(round(float(bbox[1]) * height))))
    x2 = max(x1 + 1, min(width, int(round(float(bbox[2]) * width))))
    y2 = max(y1 + 1, min(height, int(round(float(bbox[3]) * height))))
    cv2.rectangle(image, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
    cv2.putText(
        image,
        label[:42],
        (x1, max(20, y1 - 6)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        color,
        2,
        cv2.LINE_AA,
    )


def frame_card(
    frame: np.ndarray,
    timeline_frame: int,
    source_frame: int,
    group_label: str,
    boxes: Sequence[tuple[list[float], str, tuple[int, int, int]]],
    overlay: bool,
    target_width: int = 360,
) -> np.ndarray:
    image = frame.copy()
    if overlay:
        for bbox, label, color in boxes:
            draw_normalized_box(image, bbox, label, color)
    scale = target_width / image.shape[1]
    target_height = max(1, int(round(image.shape[0] * scale)))
    image = cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_AREA)
    header_height = 56
    card = np.zeros((target_height + header_height, target_width, 3), dtype=np.uint8)
    card[header_height:] = image
    cv2.putText(
        card,
        f"TL {timeline_frame} | SRC {source_frame} | {timeline_frame / TIMELINE_FPS:.3f}s",
        (8, 21),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        card,
        group_label[:48],
        (8, 45),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (210, 210, 210),
        1,
        cv2.LINE_AA,
    )
    return card


def make_sheet(cards: Sequence[np.ndarray], columns: int = 4) -> np.ndarray:
    if not cards:
        raise VisualAuthorityError("contact_sheet_has_no_cards")
    width = max(card.shape[1] for card in cards)
    height = max(card.shape[0] for card in cards)
    rows = int(math.ceil(len(cards) / columns))
    sheet = np.zeros((rows * height, columns * width, 3), dtype=np.uint8)
    for index, card in enumerate(cards):
        row = index // columns
        column = index % columns
        sheet[row * height : row * height + card.shape[0], column * width : column * width + card.shape[1]] = card
    return sheet


def resolve_video(repo_root: Path) -> Path:
    for relative in VIDEO_CANDIDATES:
        candidate = repo_root / relative
        if candidate.is_file():
            return candidate
    raise VisualAuthorityError("source_video_not_found")


def build_token_row(
    token: dict[str, Any],
    context_window: list[int],
    cue_index: dict[str, Cue],
    lifecycle_index: dict[str, dict[str, Any]],
    track_index: dict[str, dict[str, Any]],
    style_events: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    token_cue_ids = [
        cue_id
        for cue_id in (
            normalize_cue_id(value)
            for value in token.get("transcript_cue_ids") or []
        )
        if cue_id
    ]
    tracks = [track_index[cue_id] for cue_id in token_cue_ids if cue_id in track_index]
    events = choose_style_events(style_events, token, context_window)
    windows = visual_windows_from_evidence(events, tracks)
    visual_window = union_window(windows)
    paths = best_track_paths(tracks)

    transcript_rows = []
    legacy_rows = []
    for cue_id in token_cue_ids:
        cue = cue_index.get(cue_id)
        if cue:
            transcript_rows.append(
                {
                    "cue_id": cue_id,
                    "text": cue.text,
                    "transcript_window": cue.transcript_window,
                }
            )
        lifecycle = lifecycle_index.get(cue_id)
        if lifecycle:
            legacy_rows.append(
                {
                    "cue_id": cue_id,
                    "current_text": lifecycle.get("text"),
                    "current_lifecycle_window": lifecycle.get("lifecycle_window"),
                    "current_timing_authority": lifecycle.get("timing_authority"),
                    "current_animation_type": lifecycle.get("animation_type_step_3C"),
                    "authoritative": False,
                }
            )

    evidence_sources: list[dict[str, Any]] = []
    for event in events:
        evidence_sources.append(
            {
                "type": "source_style_event",
                "id": event.get("event_id"),
                "cue_id": normalize_cue_id(event.get("cue_id")),
                "observed_text": event.get("observed_text"),
                "window": style_event_window(event),
                "normalized_bbox": style_event_bbox(event),
                "confidence": round(confidence_score(event), 6),
            }
        )
    for track in tracks:
        observations = track_observations(track)
        evidence_sources.append(
            {
                "type": "source_word_instance_track",
                "id": normalize_cue_id(track.get("cue_id")),
                "accepted_source_instance": track.get("accepted_source_instance"),
                "source_exactness": track.get("source_exactness"),
                "observation_count": len(observations),
                "window": (
                    [
                        int(observations[0]["timeline_frame"]),
                        int(observations[-1]["timeline_frame"]) + 1,
                    ]
                    if observations
                    else None
                ),
                "confidence": track.get("confidence"),
            }
        )

    visual_only = token.get("visual_kind") != "text" or not token_cue_ids
    if visual_window is not None:
        status = "draft_visual_window_from_source_evidence"
    elif visual_only:
        status = "visual_only_component_requires_manual_source_review"
    else:
        status = "source_evidence_incomplete_manual_review_required"

    return {
        "visual_token_id": token["visual_token_id"],
        "visual_kind": token.get("visual_kind"),
        "display_text": token.get("display_text"),
        "text_authority": token.get("text_authority"),
        "transcript_aliases": token.get("transcript_aliases") or [],
        "transcript_links": transcript_rows,
        "legacy_transcript_first_state": legacy_rows,
        "expected_role": token.get("expected_role"),
        "expected_spatial_role": token.get("expected_spatial_role"),
        "expected_persistence": token.get("expected_persistence"),
        "expected_animation": token.get("expected_animation"),
        "visual_window": visual_window,
        "visual_window_authority": (
            "source_style_and_tracking_evidence" if visual_window is not None else "unresolved"
        ),
        "visual_window_candidates": windows,
        "position_path": paths["position_path"],
        "size_path": paths["size_path"],
        "opacity_path": paths["opacity_path"],
        "source_track_id": paths["source_track_id"],
        "style_fingerprint": style_fingerprint(events),
        "animation_evidence": animation_evidence(events),
        "evidence_sources": evidence_sources,
        "status": status,
        "transcript_timing_promoted_to_authority": False,
    }


def build_group(
    group: dict[str, Any],
    cue_index: dict[str, Cue],
    lifecycle_index: dict[str, dict[str, Any]],
    track_index: dict[str, dict[str, Any]],
    style_events: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    seed_ids = [
        cue_id
        for cue_id in (
            normalize_cue_id(value)
            for value in group.get("search_seed_cue_ids") or []
        )
        if cue_id
    ]
    missing = sorted(set(seed_ids) - set(cue_index))
    if missing:
        raise VisualAuthorityError(
            f"group_missing_transcript_seed:{group.get('group_id')}:{','.join(missing)}"
        )
    padding = int(group.get("context_padding_frames") or 18)
    context_window = context_window_from_cues(seed_ids, cue_index, padding)
    token_rows = [
        build_token_row(
            token,
            context_window,
            cue_index,
            lifecycle_index,
            track_index,
            style_events,
        )
        for token in group.get("visual_tokens") or []
    ]
    if not token_rows:
        raise VisualAuthorityError(f"group_has_no_visual_tokens:{group.get('group_id')}")

    source_evidence_count = sum(len(token["evidence_sources"]) for token in token_rows)
    unresolved = [
        token["visual_token_id"]
        for token in token_rows
        if token["visual_window"] is None
    ]

    return {
        "group_id": group["group_id"],
        "label": group.get("label"),
        "authority": "source_video_pixels_and_source_derived_visual_evidence",
        "search_seed_authority": "transcript_search_seed_only",
        "context_timeline_window": context_window,
        "search_seed_cue_ids": seed_ids,
        "reported_failures": group.get("reported_failures") or [],
        "expected_group_behavior": group.get("expected_group_behavior") or {},
        "expected_layer_order": group.get("expected_layer_order") or [],
        "visual_tokens": token_rows,
        "source_evidence_count": source_evidence_count,
        "unresolved_visual_token_ids": unresolved,
        "status": (
            "pilot_evidence_ready_for_visual_review"
            if source_evidence_count > 0
            else "pilot_evidence_missing"
        ),
    }


def build_contact_sheets(
    output_dir: Path,
    video_path: Path,
    groups: Sequence[dict[str, Any]],
    style_events: Sequence[dict[str, Any]],
    track_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise VisualAuthorityError(f"video_open_failed:{video_path}")
    source_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    source_frame_count = int(round(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0))
    if source_fps <= 0 or source_frame_count <= 0:
        capture.release()
        raise VisualAuthorityError("invalid_video_metadata")

    results: list[dict[str, Any]] = []
    try:
        for group in groups:
            group_dir = output_dir / "windows" / group["group_id"]
            group_dir.mkdir(parents=True, exist_ok=True)
            group_tracks = [
                track_index[cue_id]
                for cue_id in group["search_seed_cue_ids"]
                if cue_id in track_index
            ]
            group_events = []
            for event in style_events:
                event_window = style_event_window(event)
                if event_window is None:
                    continue
                if (
                    event_window[1] >= group["context_timeline_window"][0]
                    and event_window[0] <= group["context_timeline_window"][1]
                ):
                    group_events.append(event)

            sample_frames = sample_frames_for_group(
                group["context_timeline_window"],
                group["visual_tokens"],
            )
            plain_cards: list[np.ndarray] = []
            overlay_cards: list[np.ndarray] = []
            frame_rows: list[dict[str, Any]] = []
            for timeline_frame_value in sample_frames:
                source_frame = timeline_to_source_frame(timeline_frame_value, source_fps)
                source_frame = max(0, min(source_frame_count - 1, source_frame))
                frame = read_video_frame(capture, source_frame)
                track_boxes = nearest_track_bbox(group_tracks, timeline_frame_value)
                style_boxes = active_style_boxes(group_events, timeline_frame_value)
                boxes: list[tuple[list[float], str, tuple[int, int, int]]] = []
                boxes.extend((bbox, f"track:{label}", (0, 255, 0)) for bbox, label in track_boxes)
                boxes.extend((bbox, f"style:{label}", (0, 165, 255)) for bbox, label in style_boxes)
                plain_cards.append(
                    frame_card(
                        frame,
                        timeline_frame_value,
                        source_frame,
                        group["label"],
                        boxes,
                        overlay=False,
                    )
                )
                overlay_cards.append(
                    frame_card(
                        frame,
                        timeline_frame_value,
                        source_frame,
                        group["label"],
                        boxes,
                        overlay=True,
                    )
                )
                frame_rows.append(
                    {
                        "timeline_frame": timeline_frame_value,
                        "source_frame": source_frame,
                        "seconds": round(timeline_frame_value / TIMELINE_FPS, 6),
                        "track_box_count": len(track_boxes),
                        "style_box_count": len(style_boxes),
                    }
                )

            plain_path = group_dir / "source_contact_sheet.jpg"
            overlay_path = group_dir / "visual_evidence_overlay_contact_sheet.jpg"
            if not cv2.imwrite(str(plain_path), make_sheet(plain_cards)):
                raise VisualAuthorityError(f"contact_sheet_write_failed:{plain_path}")
            if not cv2.imwrite(str(overlay_path), make_sheet(overlay_cards)):
                raise VisualAuthorityError(f"contact_sheet_write_failed:{overlay_path}")
            write_json(
                group_dir / "frame_evidence.json",
                {
                    "group_id": group["group_id"],
                    "context_timeline_window": group["context_timeline_window"],
                    "sample_frames": frame_rows,
                    "legend": {
                        "green": "source word-instance track bbox",
                        "orange": "source style-event bbox",
                    },
                },
            )
            results.append(
                {
                    "group_id": group["group_id"],
                    "source_contact_sheet": str(plain_path),
                    "overlay_contact_sheet": str(overlay_path),
                    "frame_evidence": str(group_dir / "frame_evidence.json"),
                    "sample_frame_count": len(frame_rows),
                }
            )
    finally:
        capture.release()
    return results


def build_summary(manifest: dict[str, Any]) -> str:
    lines = [
        "# Step 3D-V1 Visual-First Authority Pilot",
        "",
        f"Task: `{manifest['task_id']}`",
        "",
        "## Authority decision",
        "",
        "Source video pixels and source-derived visual evidence are primary. "
        "Transcript cues are retained only as search seeds and canonical text aliases.",
        "",
        "## Pilot groups",
        "",
    ]
    for group in manifest["groups"]:
        lines.append(
            f"- `{group['group_id']}` — {group['label']}: "
            f"{len(group['visual_tokens'])} visual component(s), "
            f"{group['source_evidence_count']} source-evidence record(s), "
            f"{len(group['unresolved_visual_token_ids'])} unresolved component(s)."
        )
    lines.extend(
        [
            "",
            "## Rejected assumptions",
            "",
        ]
    )
    for assumption in manifest["authority_policy"]["forbidden_assumptions"]:
        lines.append(f"- {assumption}")
    lines.extend(
        [
            "",
            "## Stop boundary",
            "",
            "This artifact is an offline pilot authority draft. It does not modify Resolve, "
            "does not promote transcript timing, and does not authorize a full rollout. "
            "The seven source contact sheets must be reviewed before a seven-window Resolve pilot.",
            "",
        ]
    )
    return "\n".join(lines)


def build(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    contract_path = repo_root / CONTRACT_RELATIVE
    lifecycle_path = repo_root / LIFECYCLE_RELATIVE
    tracks_path = repo_root / TRACKS_RELATIVE
    style_path = repo_root / STYLE_RELATIVE
    srt_path = repo_root / SRT_RELATIVE
    for required in (contract_path, lifecycle_path, tracks_path, style_path, srt_path):
        if not required.is_file():
            raise VisualAuthorityError(f"required_input_missing:{required}")

    contract = load_json(contract_path)
    lifecycle = load_json(lifecycle_path)
    tracks = load_json(tracks_path)
    style = load_json(style_path)
    cues = parse_srt(srt_path)
    cue_index = {cue.cue_id: cue for cue in cues}
    lifecycle_index = unique_index(lifecycle.get("layers") or [], "cue_id", "lifecycle_cue")
    track_index = unique_index(tracks.get("tracks") or [], "cue_id", "track_cue")
    style_events = [
        row
        for row in style.get("caption_style_events") or []
        if isinstance(row, dict)
    ]

    if contract.get("task_id") != TASK_ID:
        raise VisualAuthorityError("contract_task_id_mismatch")
    pilot_groups = contract.get("pilot_groups")
    if not isinstance(pilot_groups, list) or len(pilot_groups) != 7:
        raise VisualAuthorityError("contract_requires_seven_pilot_groups")

    video_path = resolve_video(repo_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    groups = [
        build_group(
            group,
            cue_index,
            lifecycle_index,
            track_index,
            style_events,
        )
        for group in pilot_groups
    ]
    contact_sheets = build_contact_sheets(
        output_dir,
        video_path,
        groups,
        style_events,
        track_index,
    )
    contact_index = {row["group_id"]: row for row in contact_sheets}
    for group in groups:
        group["review_artifacts"] = contact_index[group["group_id"]]

    visual_token_count = sum(len(group["visual_tokens"]) for group in groups)
    visual_only_count = sum(
        1
        for group in groups
        for token in group["visual_tokens"]
        if token["visual_kind"] != "text" or token["text_authority"] == "visual_only"
    )
    unresolved_count = sum(
        len(group["unresolved_visual_token_ids"])
        for group in groups
    )
    source_evidence_count = sum(group["source_evidence_count"] for group in groups)

    manifest = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "ok": True,
        "video_id": contract.get("video_id"),
        "video": {
            "path": str(video_path),
            "sha256": file_hash(video_path),
        },
        "authority_policy": contract["authority_policy"],
        "inputs": {
            "contract": str(contract_path),
            "contract_semantic_sha256": canonical_hash(contract),
            "lifecycle": str(lifecycle_path),
            "lifecycle_semantic_sha256": canonical_hash(lifecycle),
            "tracks": str(tracks_path),
            "tracks_semantic_sha256": canonical_hash(tracks),
            "style": str(style_path),
            "style_semantic_sha256": canonical_hash(style),
            "srt": str(srt_path),
            "srt_sha256": file_hash(srt_path),
        },
        "summary": {
            "pilot_group_count": len(groups),
            "visual_token_count": visual_token_count,
            "visual_only_component_count": visual_only_count,
            "source_evidence_record_count": source_evidence_count,
            "unresolved_visual_component_count": unresolved_count,
            "transcript_timing_promoted_count": 0,
            "resolve_modified": False,
            "full_rollout_authorized": False,
        },
        "groups": groups,
        "next_boundary": {
            "objective": "seven_window_visual_pilot_after_contact_sheet_review",
            "requires_user_visual_approval": True,
            "resolve_action_allowed": False,
            "stop_condition": "do_not_build_or_modify_full_timeline_from_this_draft",
        },
    }
    manifest["semantic_sha256"] = canonical_hash(manifest)
    write_json(output_dir / "visual_authority_pilot.json", manifest)
    write_text(output_dir / "PILOT_SUMMARY.md", build_summary(manifest))
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    output_dir = args.output_dir.resolve()
    try:
        manifest = build(repo_root, output_dir)
    except Exception as exc:  # noqa: BLE001 - terminal CLI report
        print(f"FAIL {TASK_ID}: {type(exc).__name__}: {exc}")
        return 1
    print(
        "PASS "
        f"{TASK_ID}: groups={manifest['summary']['pilot_group_count']} "
        f"tokens={manifest['summary']['visual_token_count']} "
        f"evidence={manifest['summary']['source_evidence_record_count']} "
        f"unresolved={manifest['summary']['unresolved_visual_component_count']}"
    )
    print(output_dir / "visual_authority_pilot.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
