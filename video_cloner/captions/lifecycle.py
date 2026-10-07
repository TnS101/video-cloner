#!/usr/bin/env python3
"""Generate compiler-safe caption lifecycle authority from dense source evidence."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Callable, Mapping, Sequence

from scripts.davinci import caption_animation_step_3C as animation_normalizer
from scripts.davinci import caption_lifecycle_authority_step_3D as composer
from video_cloner.resolve import fcpxml as canonical
from scripts.davinci import redetect_caption_lifecycle_step_3D as dense
from video_cloner.captions.textplus import prepare_textplus_authority


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


def _display_text_decisions(value: Mapping[str, object] | None) -> dict[str, dict]:
    if value is None:
        return {}
    if (
        not isinstance(value, Mapping)
        or value.get("schema") != "video_cloner_reel_display_text_authority"
        or value.get("schema_version") != 1
        or not isinstance(value.get("decisions"), list)
    ):
        raise LifecycleGenerationError("display text authority is malformed")
    result: dict[str, dict] = {}
    for row in value["decisions"]:
        if not isinstance(row, Mapping):
            raise LifecycleGenerationError("display text decision is malformed")
        identity = str(row.get("visual_event_identity") or "").strip()
        source_text = str(row.get("source_text") or "")
        display_text = str(row.get("display_text") or "").strip()
        authority = str(row.get("authority") or "")
        evidence = row.get("evidence")
        valid_evidence = isinstance(evidence, list) and bool(evidence) and all(
            isinstance(item, Mapping)
            and bool(str(item.get("path") or "").strip())
            and len(str(item.get("sha256") or "")) == 64
            and all(character in "0123456789abcdef" for character in str(item.get("sha256") or "").lower())
            and bool(str(item.get("kind") or "").strip())
            for item in evidence
        )
        if (
            not identity or identity in result or not source_text or not display_text
            or authority not in {"confirmed_semantic_correction", "confirmed_source_observed"}
            or not valid_evidence
        ):
            raise LifecycleGenerationError("display text decision is malformed or duplicated")
        result[identity] = {**dict(row), "evidence": [dict(item) for item in evidence]}
    return result


def _source_visible_recovery_events(
    value: Mapping[str, object] | None,
    events: Sequence[Mapping[str, object]],
    source_fps: float,
    width: int,
    height: int,
) -> list[dict]:
    rows = value.get("source_visible_recoveries", []) if isinstance(value, Mapping) else []
    if not isinstance(rows, list):
        raise LifecycleGenerationError("source-visible recoveries are malformed")
    by_identity = {
        str(event.get("visual_event_identity") or ""): event
        for event in events
        if event.get("visual_event_identity")
    }
    recovered: list[dict] = []
    seen = set(by_identity)
    for row in rows:
        if not isinstance(row, Mapping):
            raise LifecycleGenerationError("source-visible recovery is malformed")
        identity = str(row.get("visual_event_identity") or "").strip()
        style_source = str(row.get("style_source_visual_identity") or "").strip()
        cue_id = str(row.get("cue_id") or "").strip()
        text = str(row.get("text") or "").strip()
        window = row.get("source_frame_window")
        bbox = row.get("bbox")
        evidence = row.get("evidence")
        if (
            not identity or identity in seen or style_source not in by_identity
            or not cue_id.startswith("sub_") or not text
            or not isinstance(window, list) or len(window) != 2 or int(window[1]) <= int(window[0])
            or not isinstance(bbox, list) or len(bbox) != 4
            or not all(isinstance(number, (int, float)) and not isinstance(number, bool) for number in bbox)
            or not isinstance(evidence, list) or not evidence
        ):
            raise LifecycleGenerationError("source-visible recovery is malformed")
        source = copy.deepcopy(by_identity[style_source])
        start, end = int(window[0]) / source_fps, int(window[1]) / source_fps
        normalized_bbox = [float(bbox[0]) / width, float(bbox[1]) / height, float(bbox[2]) / width, float(bbox[3]) / height]
        placement = source.get("placement") if isinstance(source.get("placement"), Mapping) else {}
        typography = source.get("typography") if isinstance(source.get("typography"), Mapping) else {}
        source.update({
            "event_id": f"style_event_{identity}",
            "visual_event_identity": identity,
            "cue_id": cue_id,
            "text": text,
            "observed_text": text,
            "observed_texts": [text],
            "start": start,
            "end": end,
            "tracklet_ids": [identity],
            "observation_provenance": ["human_reviewed_source_pixels"],
            "match": {"reason": "accepted", "method": "source_visible_adjudication", "cue_text": text},
            "placement": {
                **dict(placement),
                "anchor": {
                    "x": (normalized_bbox[0] + normalized_bbox[2]) / 2,
                    "y": (normalized_bbox[1] + normalized_bbox[3]) / 2,
                    "coordinate_space": "normalized_frame",
                },
                "bbox": [int(number) for number in bbox],
                "normalized_bbox": normalized_bbox,
            },
            "typography": {
                **dict(typography),
                "font_height_px": int(round(float(bbox[3]) - float(bbox[1]))),
                "font_height_ratio": (float(bbox[3]) - float(bbox[1])) / height,
            },
            "source_visible_recovery": {**dict(row), "evidence": [dict(item) for item in evidence]},
        })
        recovered.append(source)
        seen.add(identity)
    return recovered


def _associated_events(cue: Mapping[str, object], events: Sequence[Mapping[str, object]]) -> list[dict]:
    source_ids = {_cue_id(value) for value in cue.get("source_cue_ids", [cue.get("id")])}
    return [
        dict(event)
        for event in events
        if str(event.get("cue_id") or "").startswith("sub_") and _cue_id(event.get("cue_id")) in source_ids
    ]


def _accepted_event_window_track(
    cue: Mapping[str, object], events: Sequence[Mapping[str, object]], timeline_fps: float
) -> tuple[dict | None, str | None]:
    accepted: list[dict] = []
    for event in _associated_events(cue, events):
        match = event.get("match") if isinstance(event.get("match"), Mapping) else {}
        try:
            start = float(event.get("start"))
            end = float(event.get("end"))
        except (TypeError, ValueError):
            continue
        if match.get("reason") == "accepted" and math.isfinite(start) and math.isfinite(end) and end > start:
            accepted.append(event)
    if len(accepted) > 1:
        return None, "ambiguous_source_association"
    if not accepted:
        return None, None
    event = accepted[0]
    first = int(round(float(event["start"]) * timeline_fps))
    last_exclusive = max(first + 1, int(round(float(event["end"]) * timeline_fps)))
    confidence = event.get("confidence") if isinstance(event.get("confidence"), Mapping) else {}
    observations = event.get("observations") if isinstance(event.get("observations"), list) else []
    return {
        "cue_id": cue["id"],
        "text": cue["text"],
        "accepted_source_instance": True,
        "source_exactness": "accepted_visual_style_event_window",
        "confidence": {
            "label": str(confidence.get("label") or "medium"),
            "dense_observation_count": len(observations),
        },
        "geometry": {"first_visible_frame": first, "last_visible_frame": last_exclusive - 1},
        "frame_observations": [],
        "boundary_evidence": {
            "left_proven": True,
            "right_proven": True,
            "source_event_id": str(event.get("event_id") or ""),
        },
    }, None


def _accepted_motion_decision(
    value: Mapping[str, object] | None,
    authority_cues: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
) -> dict | None:
    if value is None:
        return None
    cue_id = _cue_id(value.get("cue_id"))
    visual_identity = str(value.get("visual_event_identity") or "").strip()
    evidence_id = str(value.get("style_evidence_id") or "")
    window = value.get("window")
    animation = value.get("animation")
    if (
        value.get("schema") != "video_cloner_accepted_caption_motion"
        or value.get("schema_version") != 1
        or not cue_id
        or sum(_cue_id(cue.get("id")) == cue_id for cue in authority_cues) != 1
        or (not visual_identity and not evidence_id)
        or not isinstance(window, list)
        or len(window) != 2
        or int(window[1]) <= int(window[0])
        or not isinstance(animation, Mapping)
        or animation.get("authority") != "visual_observed"
        or animation.get("source_type") != "scale"
        or animation.get("property") != "Size"
    ):
        raise LifecycleGenerationError("accepted motion decision is invalid")
    matched = [
        event for event in events
        if (
            str(event.get("visual_event_identity") or "") == visual_identity
            if visual_identity
            else str(event.get("event_id") or "") == evidence_id
        )
        and _cue_id(event.get("cue_id")) == cue_id
        and isinstance(event.get("match"), Mapping)
        and event["match"].get("reason") == "accepted"
    ]
    keyframes = animation.get("keyframes")
    duration = int(window[1]) - int(window[0])
    if (
        len(matched) != 1
        or not isinstance(keyframes, list)
        or len(keyframes) != 2
        or [int(row.get("frame", -1)) for row in keyframes if isinstance(row, Mapping)] != [0, duration - 1]
        or [float(row.get("relative_time", -1)) for row in keyframes if isinstance(row, Mapping)] != [0.0, 1.0]
        or any(
            not isinstance(row.get("value"), (int, float))
            or isinstance(row.get("value"), bool)
            or float(row["value"]) <= 0
            for row in keyframes
            if isinstance(row, Mapping)
        )
    ):
        raise LifecycleGenerationError("accepted motion decision does not match current evidence")
    source_evidence_id = str(matched[0].get("event_id") or evidence_id)
    result = {
        "cue_id": cue_id,
        "style_evidence_id": source_evidence_id,
        "window": [int(window[0]), int(window[1])],
        "animation": {
            "authority": "visual_observed",
            "source_evidence_id": source_evidence_id,
            "source_type": "scale",
            "property": "Size",
            "keyframes": [
                {
                    "frame": int(row["frame"]),
                    "relative_time": float(row["relative_time"]),
                    "value": float(row["value"]),
                }
                for row in keyframes
            ],
        },
    }
    if visual_identity:
        result["visual_event_identity"] = visual_identity
        result["animation"]["source_visual_event_identity"] = visual_identity
        if evidence_id:
            result["legacy_style_evidence_id"] = evidence_id
    return result


def _seed_events(cue: Mapping[str, object], events: Sequence[Mapping[str, object]]) -> tuple[list[dict], str | None]:
    associated = _associated_events(cue, events)
    expected = _semantic(cue.get("text"))
    eligible: list[dict] = []
    for event in associated:
        match = event.get("match") if isinstance(event.get("match"), Mapping) else {}
        observed = event.get("observed_texts")
        observations = event.get("observations")
        selected = _semantic(event.get("observed_text"))
        if not isinstance(observed, list) or len(observed) < 2 or not isinstance(observations, list):
            continue
        usable = [row for row in observations if isinstance(row, Mapping) and _semantic(row.get("text")) == expected]
        animation = event.get("animation") if isinstance(event.get("animation"), Mapping) else {}
        animation_type = str(animation.get("type") or animation.get("style") or "").strip().lower()
        if animation.get("detected") is True and animation_type in {"slide", "scale"}:
            normalized, _failure = animation_normalizer.normalize_animation_event(
                dict(event),
                {
                    "duration_frames": int(cue["end_frame"]) - int(cue["start_frame"]),
                    "base_size": 1.0,
                },
            )
            normalized_observations: list[dict] = []
            for row in usable:
                normalized_bbox = row.get("normalized_bbox")
                if not isinstance(normalized_bbox, (list, tuple)) or len(normalized_bbox) != 4:
                    normalized_observations = []
                    break
                normalized_row = dict(row)
                normalized_row["bbox"] = list(normalized_bbox)
                normalized_observations.append(normalized_row)
            if (
                event.get("event_id")
                and match.get("reason") == "accepted"
                and expected
                and selected == expected
                and len(normalized_observations) >= 2
                and normalized
                and normalized.get("animation_type") == animation_type
            ):
                eligible.append({**dict(event), "observations": normalized_observations})
            continue
        semantics = [_semantic(value) for value in observed]
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


def _visual_compositions(
    authority_cues: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
    layers: Sequence[Mapping[str, object]],
    diagnostics: Sequence[Mapping[str, object]],
    accepted_motion: Mapping[str, object] | None = None,
    timeline_fps: float = 30.0,
    display_text_authority: Mapping[str, object] | None = None,
) -> list[dict]:
    """Preserve visual grouping separately from semantic cue identity."""
    display_decisions = _display_text_decisions(display_text_authority)
    static_styles = {
        str(row.get("visual_event_identity") or ""): dict(row)
        for row in ((display_text_authority or {}).get("static_styles") or [])
        if isinstance(row, Mapping) and row.get("visual_event_identity")
    }
    accepted_visual_events: list[tuple[str, Mapping[str, object]]] = []
    seen_visual_identities: set[str] = set()
    for event in events:
        match = event.get("match") if isinstance(event.get("match"), Mapping) else {}
        if match.get("reason") != "accepted":
            continue
        visual_identity = str(event.get("visual_event_identity") or "").strip()
        if not visual_identity:
            continue
        if visual_identity in seen_visual_identities:
            raise LifecycleGenerationError(f"duplicate accepted visual_event_identity: {visual_identity}")
        seen_visual_identities.add(visual_identity)
        accepted_visual_events.append((visual_identity, event))
    missing_identities = sorted(set(display_decisions) - seen_visual_identities)
    if missing_identities:
        raise LifecycleGenerationError("display text identity is not an accepted visual event: " + ",".join(missing_identities))
    unknown_static_identities = sorted(set(static_styles) - seen_visual_identities)
    if unknown_static_identities:
        raise LifecycleGenerationError("static style identity is not an accepted visual event: " + ",".join(unknown_static_identities))

    if accepted_visual_events:
        semantic_cues_by_source: dict[str, list[Mapping[str, object]]] = {}
        for cue in authority_cues:
            for source_id in cue.get("source_cue_ids", [cue.get("id")]):
                normalized = _cue_id(source_id)
                if normalized:
                    semantic_cues_by_source.setdefault(normalized, []).append(cue)

        units: list[dict] = []
        for visual_identity, event in accepted_visual_events:
            try:
                start = float(event.get("start"))
                end = float(event.get("end"))
            except (TypeError, ValueError) as error:
                raise LifecycleGenerationError(f"invalid accepted visual event window: {visual_identity}") from error
            if not math.isfinite(start) or not math.isfinite(end) or end <= start:
                raise LifecycleGenerationError(f"invalid accepted visual event window: {visual_identity}")
            window = [int(round(start * timeline_fps)), int(round(end * timeline_fps))]
            window[1] = max(window[0] + 1, window[1])
            source_cue_id = str(event.get("cue_id") or "")
            matched_cues = semantic_cues_by_source.get(_cue_id(source_cue_id), []) if source_cue_id.startswith("sub_") else []
            semantic_ids = list(dict.fromkeys(
                _cue_id(value)
                for cue in matched_cues
                for value in cue.get("source_cue_ids", [cue.get("id")])
                if _cue_id(value)
            ))
            source_text = str(event.get("text") or "")
            display_decision = display_decisions.get(visual_identity)
            if display_decision and display_decision["source_text"] != source_text:
                raise LifecycleGenerationError(f"stale display text decision: {visual_identity}")
            token = {
                "token_id": f"visual_token_{visual_identity}",
                "text": display_decision["display_text"] if display_decision else source_text,
                "semantic_ids": semantic_ids,
                "semantic_cue_id": source_cue_id,
                "window": window,
                "visual_event_identity": visual_identity,
            }
            for source_key, target_key in (
                ("style_profile_id", "style_ref"),
                ("event_id", "style_evidence_id"),
                ("continuous_visual_identity_id", "continuous_visual_identity_id"),
                ("tracklet_ids", "tracklet_ids"),
                ("observation_provenance", "observation_provenance"),
                ("semantic_reference", "semantic_reference"),
            ):
                if event.get(source_key) not in (None, "", []):
                    token[target_key] = event[source_key]
            if display_decision:
                token["display_text_authority"] = display_decision["authority"]
                token["display_text_evidence"] = display_decision["evidence"]
            if visual_identity in static_styles:
                token["static_style"] = static_styles[visual_identity]
            if matched_cues:
                token["semantic_cues"] = [
                    {
                        "cue_id": str(cue.get("id") or ""),
                        "text": str(cue.get("text") or ""),
                        "source_cue_ids": [_cue_id(value) for value in cue.get("source_cue_ids", [cue.get("id")])],
                    }
                    for cue in matched_cues
                ]
            if accepted_motion and visual_identity == accepted_motion.get("visual_event_identity"):
                window = [int(value) for value in accepted_motion["window"]]
                token["window"] = window
                token["style_evidence_id"] = str(accepted_motion["style_evidence_id"])
                token["accepted_motion_authority"] = dict(accepted_motion["animation"])
            evidence_id = str(event.get("event_id") or "")
            units.append({
                "composition_id": f"visual_composition_{visual_identity}",
                "window": list(window),
                "relation": {"mode": "single", "predecessor_token_ids": []},
                "authority": {
                    "kind": "visual_primary",
                    "evidence_ids": [evidence_id] if evidence_id else [],
                    "reason": "accepted_normalized_visual_event",
                },
                "tokens": [token],
            })

        units.sort(key=lambda row: (row["window"][0], row["window"][1], row["tokens"][0]["visual_event_identity"]))
        compositions: list[dict] = []
        for unit in units:
            previous = compositions[-1] if compositions else None
            if previous and unit["window"][0] < previous["window"][1]:
                previous["tokens"].extend(unit["tokens"])
                previous["window"][1] = max(previous["window"][1], unit["window"][1])
                previous["relation"]["mode"] = "simultaneous"
                previous["authority"]["evidence_ids"].extend(unit["authority"]["evidence_ids"])
                previous["composition_id"] += "__" + unit["composition_id"].removeprefix("visual_composition_")
            else:
                compositions.append(unit)
        return compositions

    # Legacy cue-owned fallback is retained only for inputs that predate visual identity authority.
    layer_by_id = {str(layer.get("cue_id") or ""): layer for layer in layers}
    diagnostic_by_id = {str(row.get("cue_id") or ""): row for row in diagnostics}
    units: list[dict] = []
    for cue in authority_cues:
        cue_id = str(cue["id"])
        semantic_ids = [_cue_id(value) for value in cue.get("source_cue_ids", [cue_id])]
        associated = _associated_events(cue, events)
        evidence_ids = [str(event.get("event_id") or "") for event in associated if event.get("event_id")]
        layer = layer_by_id[cue_id]
        diagnostic = diagnostic_by_id.get(cue_id)
        if diagnostic:
            kind = "unresolved"
            reason = str(diagnostic.get("reason") or "conflicting_visual_evidence")
        elif layer.get("timing_authority") == "visual_primary":
            kind = "visual_primary"
            reason = str(layer.get("visual_source_exactness") or "accepted_dense_visual_track")
        else:
            kind = "transcript_fallback"
            reason = "no_accepted_visual_evidence"
        window = [int(value) for value in layer["lifecycle_window"]]
        motion_event = next((
            event for event in associated
            if accepted_motion
            and cue_id == accepted_motion.get("cue_id")
            and event.get("visual_event_identity") == accepted_motion.get("visual_event_identity")
        ), None)
        event = motion_event or (associated[0] if len(associated) == 1 else {})
        token = {
            "token_id": f"visual_token_{cue_id}",
            "text": str(cue["text"]),
            "semantic_ids": semantic_ids,
            "window": list(window),
        }
        if event.get("style_profile_id"):
            token["style_ref"] = event["style_profile_id"]
        match = event.get("match") if isinstance(event.get("match"), Mapping) else {}
        if event.get("event_id") and match.get("reason") == "accepted":
            token["style_evidence_id"] = str(event["event_id"])
        if accepted_motion and cue_id == accepted_motion.get("cue_id"):
            if accepted_motion.get("visual_event_identity"):
                token["visual_event_identity"] = str(accepted_motion["visual_event_identity"])
            token["accepted_motion_authority"] = dict(accepted_motion["animation"])
        units.append({
            "composition_id": f"visual_composition_{cue_id}",
            "window": window,
            "relation": {"mode": "single", "predecessor_token_ids": []},
            "authority": {"kind": kind, "evidence_ids": evidence_ids, "reason": reason},
            "tokens": [token],
        })

    # Overlapping accepted visual tokens are one simultaneous on-screen state.
    compositions: list[dict] = []
    for unit in units:
        previous = compositions[-1] if compositions else None
        if (
            previous
            and previous["authority"]["kind"] == "visual_primary"
            and unit["authority"]["kind"] == "visual_primary"
            and unit["window"][0] < previous["window"][1]
        ):
            previous["tokens"].extend(unit["tokens"])
            previous["window"][0] = min(previous["window"][0], unit["window"][0])
            previous["window"][1] = max(previous["window"][1], unit["window"][1])
            previous["relation"]["mode"] = "simultaneous"
            previous["authority"]["evidence_ids"].extend(unit["authority"]["evidence_ids"])
            previous["composition_id"] += "__" + unit["composition_id"].removeprefix("visual_composition_")
        else:
            compositions.append(unit)
    return compositions


def generate_lifecycle(
    authority_cues: Sequence[Mapping[str, object]],
    style_data: Mapping[str, object],
    source_video: str | Path,
    timeline_fps: float,
    *,
    search_padding_seconds: float = 0.75,
    tracker: Callable[..., dict] = _dense_track,
    accepted_motion: Mapping[str, object] | None = None,
    display_text_authority: Mapping[str, object] | None = None,
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
    recovery_events = _source_visible_recovery_events(
        display_text_authority, events, source_fps, width, height
    )
    events.extend(recovery_events)
    accepted_motion = _accepted_motion_decision(accepted_motion, authority_cues, events)
    tracks: list[dict] = []
    diagnostics: list[dict] = []
    try:
        for cue in authority_cues:
            candidates, reason = _seed_events(cue, events)
            candidate_animation = candidates[0].get("animation") if len(candidates) == 1 else None
            motion_candidate = isinstance(candidate_animation, Mapping) and candidate_animation.get("detected") is True
            if motion_candidate:
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
                    continue
                except Exception:
                    pass
            direct_track, direct_reason = _accepted_event_window_track(cue, events, timeline_fps)
            if direct_reason:
                diagnostics.append({"cue_id": cue["id"], "state": "needs_redetection", "reason": direct_reason})
                continue
            if direct_track:
                tracks.append(direct_track)
                continue
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

    if accepted_motion:
        accepted_cue_id = str(accepted_motion["cue_id"])
        accepted_window = accepted_motion["window"]
        accepted_cue = next(cue for cue in authority_cues if _cue_id(cue.get("id")) == accepted_cue_id)
        for track in tracks:
            if (
                track.get("cue_id") != accepted_cue_id
                and track.get("source_exactness") == "source_video_dense_template_track"
            ):
                track["source_exactness"] = "source_video_dense_template_track_observation_only"
        tracks = [track for track in tracks if track.get("cue_id") != accepted_cue_id]
        tracks.append({
            "cue_id": accepted_cue_id,
            "text": accepted_cue["text"],
            "accepted_source_instance": True,
            "source_exactness": "source_video_dense_template_track",
            "confidence": {"label": "accepted", "dense_observation_count": 0},
            "geometry": {
                "first_visible_frame": int(accepted_window[0]),
                "last_visible_frame": int(accepted_window[1]) - 1,
            },
            "frame_observations": [],
            "boundary_evidence": {
                "left_proven": True,
                "right_proven": True,
                "source_event_id": accepted_motion["style_evidence_id"],
                "product_motion_acceptance": "explicit",
            },
        })
        diagnostics = [row for row in diagnostics if row.get("cue_id") != accepted_cue_id]

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
    result["visual_compositions"] = _visual_compositions(
        authority_cues, events, result["layers"], diagnostics, accepted_motion, timeline_fps,
        display_text_authority,
    )
    result["accepted_motion_decision"] = accepted_motion
    result["source_visible_recovery_events"] = recovery_events
    result["summary"]["needs_redetection_count"] = len(diagnostics)
    result["summary"]["needs_redetection_cue_ids"] = [row["cue_id"] for row in diagnostics]
    result["summary"]["visual_composition_count"] = len(result["visual_compositions"])
    result["summary"]["visual_token_count"] = sum(len(row["tokens"]) for row in result["visual_compositions"])
    result["summary"]["visual_primary_object_count"] = sum(
        len(composition["tokens"])
        for composition in result["visual_compositions"]
        if composition["authority"]["kind"] == "visual_primary"
    )
    result["summary"]["identity_linked_visual_object_count"] = sum(
        bool(token.get("visual_event_identity"))
        for composition in result["visual_compositions"]
        for token in composition["tokens"]
    )
    result["summary"]["unresolved_visual_composition_count"] = sum(
        row["authority"]["kind"] == "unresolved" for row in result["visual_compositions"]
    )
    result["summary"]["visual_style_event_window_count"] = sum(
        layer.get("visual_source_exactness") == "accepted_visual_style_event_window" for layer in result["layers"]
    )
    result["summary"]["dense_tracker_count"] = sum(
        str(layer.get("visual_source_exactness") or "").startswith("source_video_dense_template_track")
        for layer in result["layers"]
    )
    result["summary"]["accepted_product_motion_count"] = int(accepted_motion is not None)
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
    accepted_motion_path: str | Path | None = None,
    display_text_authority_path: str | Path | None = None,
) -> dict:
    generic = json.loads(Path(generic_path).read_text(encoding="utf-8-sig"))
    style = json.loads(Path(caption_style_path).read_text(encoding="utf-8-sig"))
    motion_path = Path(accepted_motion_path) if accepted_motion_path else (
        Path(__file__).parents[2] / "config" / f"{generic.get('video_id')}.accepted_caption_motion.json"
    )
    display_path = Path(display_text_authority_path) if display_text_authority_path else (
        Path(__file__).parents[2] / "config" / f"{generic.get('video_id')}.display_text_authority.json"
    )
    prepared = prepare_textplus_authority(generic, style)
    display_authority = json.loads(display_path.read_text(encoding="utf-8-sig")) if display_path.is_file() else None
    if display_authority and (display_authority.get("video_id") != generic.get("video_id") or display_authority.get("source_video_sha256") != _sha256(Path(source_video).expanduser().resolve())):
        raise LifecycleGenerationError("display text authority does not match the source video")
    result = generate_lifecycle(
        prepared["cues"], style, source_video, float(prepared["fps"]),
        search_padding_seconds=search_padding_seconds,
        accepted_motion=(
            json.loads(motion_path.read_text(encoding="utf-8-sig")) if motion_path.is_file() else None
        ),
        display_text_authority=display_authority,
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
    parser.add_argument("--accepted-motion")
    parser.add_argument("--display-text-authority")
    parser.add_argument("--search-padding-seconds", type=float, default=0.75)
    args = parser.parse_args()
    try:
        result = generate_from_files(
            args.generic, args.caption_style, args.source_video, args.output,
            search_padding_seconds=args.search_padding_seconds,
            accepted_motion_path=args.accepted_motion,
            display_text_authority_path=args.display_text_authority,
        )
    except Exception as error:
        print(json.dumps({"ok": False, "error": f"{type(error).__name__}: {error}"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": result["ok"], "summary": result["summary"], "output": str(Path(args.output).resolve())}, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
