"""Build source-derived caption compositions from canonical caption observations."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.standalone.video_cloner_composition_relationships import build_composition_graph


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"object_required:{path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _window(start: float, end: float, fps: float) -> list[int]:
    first = int(round(start * fps))
    return [first, max(first + 1, int(round(end * fps)))]


def _event_index(style: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    events = style.get("caption_style_events") or style.get("style_events") or []
    result: dict[str, dict[str, Any]] = {}
    for event in events:
        identity = str(event.get("visual_event_identity") or "")
        if identity:
            if identity in result:
                raise ValueError(f"duplicate_visual_identity:{identity}")
            result[identity] = dict(event)
    return result


def _lifecycle_token_index(lifecycle: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for composition in lifecycle.get("visual_compositions") or []:
        for token in composition.get("tokens") or []:
            identity = str(token.get("visual_event_identity") or "")
            if not identity:
                continue
            if identity in result:
                raise ValueError(f"duplicate_lifecycle_identity:{identity}")
            result[identity] = dict(token)
    return result


def _recipe_index(recipes: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for recipe in recipes.get("recipes") or []:
        provenance = recipe.get("provenance") if isinstance(recipe.get("provenance"), Mapping) else {}
        event_id = str(provenance.get("localization_event_id") or "")
        if event_id:
            result.setdefault(event_id, []).append(dict(recipe))
    return result


def _slide_references(style: Mapping[str, Any], recipes: Mapping[str, Any], style_path: Path) -> list[dict[str, Any]]:
    sources = recipes.get("sources") or {}
    video = sources.get("video") or {}
    video_path = Path(str(video.get("path") or ""))
    if not video_path.is_absolute():
        video_path = ROOT / video_path
    if not recipes.get("decision") or not video_path.is_file() or _sha256(video_path) != video.get("sha256"):
        return []
    localization_hash_matches = (sources.get("localization") or {}).get("sha256") == _sha256(style_path)
    info = style.get("video_info") or {}
    width, height = float(info.get("width") or 0), float(info.get("height") or 0)
    if width <= 0 or height <= 0:
        return []
    events = {event.get("event_id"): event for event in _event_index(style).values()}
    result = []
    for recipe in recipes.get("recipes") or []:
        provenance = recipe.get("provenance") or {}
        event_id = provenance.get("localization_event_id")
        event = events.get(event_id)
        positions = (recipe.get("channels") or {}).get("position") or []
        timestamps = provenance.get("sample_timestamps") or []
        if not event or len(positions) < 2 or len(timestamps) < 3:
            continue
        observations = sorted((row for row in event.get("observations") or []
                               if isinstance(row, Mapping) and isinstance(row.get("bbox"), list)
                               and len(row["bbox"]) == 4 and isinstance(row.get("timestamp"), (int, float))),
                              key=lambda row: row["timestamp"])
        sampled = [row for row in observations if any(abs(row["timestamp"] - t) <= 0.035 for t in timestamps)]
        texts = ["".join(ch for ch in str(row.get("text") or "").casefold() if ch.isalnum()) for row in sampled]
        dominant = Counter(texts).most_common(1)
        if not dominant or not dominant[0][0] or dominant[0][1] < max(3, 0.7 * len(timestamps)):
            continue
        stable = [row for row in sampled if "".join(ch for ch in str(row.get("text") or "").casefold() if ch.isalnum()) == dominant[0][0]]
        first, last = stable[0], stable[-1]
        if last["timestamp"] <= first["timestamp"]:
            continue
        a, b = first["bbox"], last["bbox"]
        edges = [(b[i] - a[i]) / (width if i % 2 == 0 else height) for i in range(4)]
        motion = ((edges[0] + edges[2]) / 2, (edges[1] + edges[3]) / 2)
        measured = [float(positions[-1]["value"][i]) - float(positions[0]["value"][i]) for i in (0, 1)]
        length, recipe_length = math.hypot(*motion), math.hypot(*measured)
        if length < 0.02 or recipe_length <= 0 or not 0.4 <= length / recipe_length <= 2.5:
            continue
        direction = sum(x * y for x, y in zip(motion, measured)) / (length * recipe_length)
        axis = (edges[0], edges[2]) if abs(motion[0]) >= abs(motion[1]) else (edges[1], edges[3])
        parallel = max(0.0, 1 - abs(axis[0] - axis[1]) / (abs(axis[0]) + abs(axis[1]) + 1e-9))
        if direction < 0.8 or parallel < 0.65:
            continue
        centers = [((row["bbox"][0] + row["bbox"][2]) / (2 * width),
                    (row["bbox"][1] + row["bbox"][3]) / (2 * height)) for row in stable]
        middle = min(range(len(stable)), key=lambda i: abs((stable[i]["timestamp"] - first["timestamp"]) /
                                                           (last["timestamp"] - first["timestamp"]) - 0.5))
        midpoint = sum((centers[middle][i] - centers[0][i]) * motion[i] for i in (0, 1)) / length**2
        result.append({
            "reel": recipes.get("reel"), "visual_identity": event.get("visual_event_identity"),
            "event_id": event_id, "recipe_id": recipe.get("caption_id"), "motion": motion,
            "parallel": parallel, "midpoint": midpoint,
            "provenance": {"decision": recipes["decision"], "route": provenance.get("route"),
                           "source_video_sha256": video["sha256"],
                           "localization_sha256_matches_current_style": localization_hash_matches,
                           "sample_timestamps": timestamps},
        })
    return result


def _animation_candidates(event: Mapping[str, Any], width: float, height: float,
                          recipe_matches: Sequence[Mapping[str, Any]],
                          references: Sequence[Mapping[str, Any]] = (), reel: str = "") -> dict[str, Any]:
    rows = sorted((row for row in event.get("observations") or []
                   if isinstance(row, Mapping)
                   and isinstance(row.get("bbox"), list) and len(row["bbox"]) == 4
                   and all(isinstance(value, (int, float)) and math.isfinite(value) for value in row["bbox"])
                   and row["bbox"][2] > row["bbox"][0] and row["bbox"][3] > row["bbox"][1]
                   and isinstance(row.get("timestamp"), (int, float)) and math.isfinite(row["timestamp"])),
                  key=lambda row: row["timestamp"])
    result: dict[str, Any] = {
        "score_type": "relative_similarity_not_probability",
        "observation_count": len(rows),
        "candidates": [],
    }
    if width <= 0 or height <= 0 or len(rows) < 3 or rows[-1]["timestamp"] <= rows[0]["timestamp"]:
        result.update(status="insufficient_source_observations")
        return result

    first, last = rows[0]["bbox"], rows[-1]["bbox"]
    if first[2] <= first[0] or first[3] <= first[1] or last[2] <= last[0] or last[3] <= last[1]:
        result.update(status="insufficient_source_observations")
        return result
    edges = [(last[i] - first[i]) / (width if i % 2 == 0 else height) for i in range(4)]
    center = ((edges[0] + edges[2]) / 2, (edges[1] + edges[3]) / 2)
    centers = [((row["bbox"][0] + row["bbox"][2]) / (2 * width),
                (row["bbox"][1] + row["bbox"][3]) / (2 * height)) for row in rows]
    path = sum(math.dist(a, b) for a, b in zip(centers, centers[1:]))
    temporal_consistency = math.dist(centers[0], centers[-1]) / path if path else 0.0
    width_change = ((last[2] - last[0]) / (first[2] - first[0])) - 1
    height_change = ((last[3] - last[1]) / (first[3] - first[1])) - 1
    states = list(dict.fromkeys("".join(ch for ch in str(row.get("text") or "").casefold() if ch.isalnum()) for row in rows))
    progression = len(states) > 1 and bool(states[0]) and len(states[-1]) > len(states[0]) and all(
        right.startswith(left) for left, right in zip(states, states[1:]))
    tail = rows[-3:]
    settled = len({str(row.get("text") or "").casefold() for row in tail}) == 1 and all(
        max(abs(row["bbox"][i] - last[i]) / (width if i % 2 == 0 else height) for i in range(4)) <= 0.005
        for row in tail)
    axis = (edges[0], edges[2]) if abs(center[0]) >= abs(center[1]) else (edges[1], edges[3])
    parallel = max(0.0, 1 - abs(axis[0] - axis[1]) / (abs(axis[0]) + abs(axis[1]) + 1e-9))
    movement = min(1.0, math.hypot(*center) / 0.08)
    size_change = min(1.0, max(abs(width_change), abs(height_change)) / 0.30)
    proportional = (max(0.0, 1 - abs(width_change - height_change) /
                        max(abs(width_change), abs(height_change), 0.01)) if size_change > 0.05 else 0.0)
    left_anchor = max(0.0, 1 - abs(edges[0]) / 0.01)
    height_stable = max(0.0, 1 - abs(height_change) / 0.10)
    right_growth = min(1.0, max(0.0, edges[2] - edges[0]) / 0.12)
    full_stable = max(0.0, 1 - max(abs(value) for value in edges) / 0.02)
    middle = min(range(len(rows)), key=lambda i: abs((rows[i]["timestamp"] - rows[0]["timestamp"]) /
                                                  (rows[-1]["timestamp"] - rows[0]["timestamp"]) - 0.5))
    midpoint = (sum((centers[middle][i] - centers[0][i]) * center[i] for i in (0, 1)) /
                math.hypot(*center)**2 if math.hypot(*center) else 0.0)

    facts = {
        "edge_displacement_normalized": [round(value, 5) for value in edges],
        "center_displacement_normalized": [round(value, 5) for value in center],
        "width_change_ratio": round(width_change, 5),
        "height_change_ratio": round(height_change, 5),
        "ocr_text_states": states,
        "settled_last_three_observations": settled,
        "temporal_direction_consistency": round(temporal_consistency, 5),
        "opacity": "not_measured",
    }
    scores = {
        "text_state_progression_or_reveal": (0.30 * progression + 0.20 * right_growth +
            0.20 * left_anchor + 0.15 * height_stable + 0.15 * settled) if progression else 0.0,
        "translation_slide": movement * max(0.0, 0.55 * parallel + 0.25 * movement +
            0.20 * temporal_consistency - 0.10 * progression),
        "scale_pop": max(0.0, 0.70 * proportional + 0.30 * size_change - 0.20 * progression),
        "static": max(0.0, 0.65 * full_stable + 0.25 * settled - 0.25 * progression),
    }
    evidence = {
        "text_state_progression_or_reveal": (
            ["ocr_prefix_progression"] +
            (["right_edge_growth_with_stable_left_edge"] if right_growth > 0.5 and left_anchor > 0.5 else []) +
            (["stable_final_text_state"] if settled else []),
            ["ocr_state_changes_do_not_prove_animated_reveal"]),
        "translation_slide": (
            (["center_displacement"] if movement > 0.25 else []) +
            (["temporally_consistent_direction"] if temporal_consistency > 0.5 else []),
            (["edge_displacements_do_not_match"] if parallel < 0.5 else []) +
            (["center_shift_can_follow_text_growth"] if progression else [])),
        "scale_pop": (
            ["bounding_box_size_changes"],
            (["width_and_height_do_not_scale_proportionally"] if proportional < 0.5 else []) +
            (["text_state_changes_affect_box_size"] if progression else [])),
        "static": (
            ["stable_final_observations"] if settled else ["small_full_window_displacement"],
            (["full_window_geometry_changes"] if full_stable < 0.5 else []) +
            (["ocr_text_states_change"] if progression else [])),
    }
    candidates = []
    for family, score in scores.items():
        if score <= 0:
            continue
        channels = {"translation_slide": "position", "scale_pop": "scale"}
        direct = next((recipe for recipe in recipe_matches
                       if (keys := (recipe.get("channels") or {}).get(channels.get(family)))
                       and len({str(key.get("value")) for key in keys}) > 1), None)
        support, contradiction = evidence[family]
        candidates.append({
            "family": family, "similarity": round(min(1.0, score), 3),
            "supporting_evidence": support, "contradicting_evidence": contradiction,
            "reference_kind": "direct_source_recipe" if direct else "generic_motion_signature",
            "reference_id": direct.get("caption_id") if direct else None,
            "actionable": False,
        })
        if family == "translation_slide" and references:
            options = []
            length = math.hypot(*center)
            for reference in references:
                if reference["reel"] == reel and reference["event_id"] == event.get("event_id"):
                    continue
                other = reference["motion"]
                other_length = math.hypot(*other)
                if not length or not other_length:
                    continue
                direction = max(0.0, sum(x * y for x, y in zip(center, other)) / (length * other_length))
                magnitude = math.sqrt(min(length, other_length) / max(length, other_length))
                timing = max(0.0, 1 - min(1.0, abs(midpoint - reference["midpoint"])))
                similarity = (direction * magnitude * (0.5 + 0.5 * timing) *
                              min(1.0, parallel / reference["parallel"]) * (0.35 if progression else 1.0))
                options.append((similarity, reference))
            if options and max(score for score, _ in options) > 0:
                similarity, reference = max(options, key=lambda row: (row[0], str(row[1]["recipe_id"])))
                candidates[-1].update(
                    reference_similarity=round(similarity, 3), reference_kind="source_backed_recipe",
                    reference_id=reference["recipe_id"], reference_reel=reference["reel"],
                    reference_visual_identity=reference["visual_identity"],
                    reference_recipe_id=reference["recipe_id"],
                    reference_provenance=reference["provenance"],
                )
                candidates[-1]["supporting_evidence"].append("source_observed_reference_motion_compared")
                if progression or parallel < 0.5:
                    candidates[-1]["contradicting_evidence"].append("reference_translation_conflicts_with_text_growth")
    result.update(status="ranked_hypotheses" if candidates else "insufficient_discriminating_evidence",
                  observed_features=facts,
                  candidates=sorted(candidates, key=lambda row: (-row["similarity"], row["family"]))[:3])
    return result


def _review_evidence(
    identity: str,
    review: Mapping[str, Any],
    source_fps: float,
    timeline_fps: float,
) -> list[dict[str, Any]]:
    rows = []
    frame_dir = Path(str(review.get("frame_sampling_dir") or ""))
    if frame_dir and not frame_dir.is_absolute():
        frame_dir = ROOT / frame_dir
    for evidence in (review.get("evidence") or {}).get(identity, ()):
        frame_index = int(evidence["frame_index"])
        matches = sorted(frame_dir.glob(f"frame_{frame_index:03d}_*.jpg"))
        if len(matches) != 1:
            raise ValueError(f"review_frame_not_unique:{identity}:{frame_index}:{len(matches)}")
        timestamp = float(evidence["timestamp_seconds"])
        rows.append({
            **evidence,
            "source_frame": int(round(timestamp * source_fps)),
            "timeline_frame": int(round(timestamp * timeline_fps)),
            "sample_frame_path": str(matches[0].relative_to(ROOT)),
            "sample_frame_sha256": _sha256(matches[0]),
            "authority": "TARGETED_SOURCE_FRAME_REVIEW",
        })
    return rows


def _visibility_status(
    timestamp: float,
    observations: Sequence[Mapping[str, Any]],
    review_evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    direct = [row for row in observations if abs(float(row["timestamp"]) - timestamp) < 0.001]
    reviewed = [row for row in review_evidence if abs(float(row["timestamp_seconds"]) - timestamp) < 0.001]
    positive_review = [row for row in reviewed if row["status"] == "observed_present"]
    if direct or positive_review:
        return {
            "status": "observed_present",
            "authority": "SOURCE_OCR_OBSERVATION" if direct else "TARGETED_SOURCE_FRAME_REVIEW",
            "evidence": [
                *[{"kind": "ocr", "analyzer_frame_index": int(row["frame_index"])} for row in direct],
                *[{"kind": "targeted_source_frame", "analyzer_frame_index": int(row["frame_index"]), "observed_text": row.get("observed_text")} for row in positive_review],
            ],
        }
    negative_review = [row for row in reviewed if row["status"] == "proven_absent"]
    if negative_review:
        return {
            "status": "proven_absent",
            "authority": "TARGETED_SOURCE_FRAME_REVIEW",
            "evidence": [{"kind": "targeted_source_frame", "analyzer_frame_index": int(row["frame_index"])} for row in negative_review],
        }
    positive_times = sorted(
        {float(row["timestamp"]) for row in observations}
        | {float(row["timestamp_seconds"]) for row in review_evidence if row["status"] == "observed_present"}
    )
    before = [value for value in positive_times if value < timestamp]
    after = [value for value in positive_times if value > timestamp]
    negative_times = [float(row["timestamp_seconds"]) for row in review_evidence if row["status"] == "proven_absent"]
    if before and after and not any(before[-1] < value < after[0] for value in negative_times):
        return {
            "status": "inferred_retained",
            "authority": "INFERRED_BETWEEN_POSITIVE_SOURCE_OBSERVATIONS",
            "evidence": {"previous_positive_seconds": before[-1], "next_positive_seconds": after[0]},
        }
    return {
        "status": "unknown",
        "authority": "NO_NEGATIVE_EVIDENCE",
        "reason": "no_positive_observation_on_both_sides_of_sample",
    }


def _states(
    frame_results: Sequence[Mapping[str, Any]],
    identities: Sequence[str],
    events: Mapping[str, Mapping[str, Any]],
    review_by_identity: Mapping[str, Sequence[Mapping[str, Any]]],
    source_fps: float,
    timeline_fps: float,
    window_seconds: Sequence[float],
) -> list[dict[str, Any]]:
    start, end = (float(value) for value in window_seconds)
    rows = []
    for frame in frame_results:
        timestamp = float(frame["timestamp"])
        if timestamp < start - 0.001 or timestamp > end + 0.001:
            continue
        member_evidence = {
            identity: _visibility_status(
                timestamp,
                events[identity].get("observations") or [],
                review_by_identity.get(identity, ()),
            )
            for identity in identities
        }
        rows.append({
            "at_seconds": timestamp,
            "source_frame": int(round(timestamp * source_fps)),
            "timeline_frame": int(round(timestamp * timeline_fps)),
            "analyzer_frame_index": int(frame["frame_index"]),
            "observed_member_identities": [identity for identity in identities if member_evidence[identity]["status"] == "observed_present"],
            "inferred_retained_member_identities": [identity for identity in identities if member_evidence[identity]["status"] == "inferred_retained"],
            "unknown_member_identities": [identity for identity in identities if member_evidence[identity]["status"] == "unknown"],
            "proven_absent_member_identities": [identity for identity in identities if member_evidence[identity]["status"] == "proven_absent"],
            "member_evidence": member_evidence,
            "semantics": "point_sample; an OCR omission is not negative visibility evidence",
        })
    return rows


def _co_visible_intervals(
    states: Sequence[Mapping[str, Any]], identities: Sequence[str], source_fps: float, timeline_fps: float
) -> list[dict[str, Any]]:
    spans: list[list[Mapping[str, Any]]] = []
    current: list[Mapping[str, Any]] = []
    for state in states:
        supported = set(state["observed_member_identities"]) | set(state["inferred_retained_member_identities"])
        if supported == set(identities):
            current.append(state)
        elif current:
            spans.append(current)
            current = []
    if current:
        spans.append(current)
    return [
        {
            "seconds": [float(span[0]["at_seconds"]), float(span[-1]["at_seconds"])],
            "source_frame_window": _window(float(span[0]["at_seconds"]), float(span[-1]["at_seconds"]), source_fps),
            "timeline_frame_window": _window(float(span[0]["at_seconds"]), float(span[-1]["at_seconds"]), timeline_fps),
            "member_identities": list(identities),
            "authority": "INFERRED_CONTINUITY_BETWEEN_POSITIVE_SOURCE_OBSERVATIONS",
            "semantics": "sample-supported span; endpoints are not inferred entry or exit events",
        }
        for span in spans
        if len(span) > 1
    ]


def _member(
    identity: str,
    event: Mapping[str, Any],
    lifecycle_token: Mapping[str, Any],
    review_evidence: Sequence[Mapping[str, Any]],
    recipe_matches: Sequence[Mapping[str, Any]],
    recipe_decision: str,
    source_fps: float,
    timeline_fps: float,
    source_width: float,
    source_height: float,
    references: Sequence[Mapping[str, Any]],
    reel: str,
) -> dict[str, Any]:
    observations = [dict(row) for row in event.get("observations") or []]
    if not observations:
        raise ValueError(f"missing_observations:{identity}")
    start, end = float(event["start"]), float(event["end"])
    positive_evidence = [
        {"timestamp_seconds": float(row["timestamp"]), "authority": "SOURCE_OCR_OBSERVATION"}
        for row in observations
    ] + [
        {"timestamp_seconds": float(row["timestamp_seconds"]), "authority": "TARGETED_SOURCE_FRAME_REVIEW"}
        for row in review_evidence
        if row["status"] == "observed_present"
    ]
    first_positive = min(positive_evidence, key=lambda row: row["timestamp_seconds"])
    last_positive = max(positive_evidence, key=lambda row: row["timestamp_seconds"])
    negative_before = [row for row in review_evidence if row["status"] == "proven_absent" and float(row["timestamp_seconds"]) < first_positive["timestamp_seconds"]]
    negative_after = [row for row in review_evidence if row["status"] == "proven_absent" and float(row["timestamp_seconds"]) > last_positive["timestamp_seconds"]]
    converted_timeline = _window(start, end, timeline_fps)
    lifecycle_window = [int(value) for value in lifecycle_token["window"]]
    if converted_timeline != lifecycle_window:
        raise ValueError(f"timeline_window_mismatch:{identity}:{converted_timeline}:{lifecycle_window}")
    if len(recipe_matches) == 1:
        recipe = recipe_matches[0]
        animation_link: dict[str, Any] = {
            "status": "linked",
            "match": "direct_unique_localization_event_id",
            "event_id": event["event_id"],
            "caption_id": recipe["caption_id"],
            "timeline_frame_window": [int(recipe["start_frame"]), int(recipe["start_frame"]) + int(recipe["duration"])],
            "channels": recipe["channels"],
            "recipe_confidence": recipe.get("confidence"),
            "channel_authority": "OPENCV_SOURCE_MEASUREMENT",
            "acceptance_authority": recipe_decision,
        }
    else:
        animation_link = {
            "status": "unresolved",
            "event_id": event.get("event_id"),
            "reason": "no_unique_direct_localization_event_id_match",
            "candidate_count": len(recipe_matches),
        }
    return {
        "visual_identity": identity,
        "source_observed_texts": sorted(set(str(value) for value in event.get("observed_texts") or [] if str(value))),
        "targeted_source_observed_texts": sorted(
            {str(row["observed_text"]) for row in review_evidence if row.get("observed_text")}
        ),
        "source_observations": [
            {
                "timestamp_seconds": float(row["timestamp"]),
                "source_frame": int(round(float(row["timestamp"]) * source_fps)),
                "analyzer_frame_index": int(row["frame_index"]),
                "bbox_source_pixels": [int(value) for value in row["bbox"]],
                "co_visible_tracklet_ids": list((row.get("composition") or {}).get("tracklet_ids") or []),
            }
            for row in observations
        ],
        "semantic_reference": event.get("semantic_reference"),
        "visibility": {
            "accepted_style_event_seconds": [start, end],
            "source_frame_window": _window(start, end, source_fps),
            "timeline_frame_window": lifecycle_window,
            "timeline_window_authority": lifecycle_token.get("window_authority", "CAPTION_LIFECYCLE_AUTHORITY"),
            "timeline_conversion": f"round(seconds * {timeline_fps:g})",
            "positive_evidence_span_seconds": [first_positive["timestamp_seconds"], last_positive["timestamp_seconds"]],
            "targeted_source_frame_evidence": list(review_evidence),
        },
        "phases": {
            "enter": {
                "status": "bounded_unresolved" if negative_before else "unresolved",
                "last_proven_absent_seconds": max(float(row["timestamp_seconds"]) for row in negative_before) if negative_before else None,
                "first_positive_seconds": first_positive["timestamp_seconds"],
                "reason": "entry_occurs_between_sampled_source_frames" if negative_before else "first_positive_observation_is_not_proof_of_entry",
            },
            "hold": {
                "status": "inferred_retained_between_positive_observations",
                "seconds": [first_positive["timestamp_seconds"], last_positive["timestamp_seconds"]],
                "positive_evidence_count": len(positive_evidence),
                "authority": "INFERRED_CONTINUITY; endpoints are positive source evidence",
            },
            "exit": {
                "status": "bounded_unresolved" if negative_after else "unresolved",
                "last_positive_seconds": last_positive["timestamp_seconds"],
                "first_proven_absent_seconds": min(float(row["timestamp_seconds"]) for row in negative_after) if negative_after else None,
                "reason": "exit_occurs_between_sampled_source_frames" if negative_after else "no_negative_boundary_or_direct_exit_channel_evidence",
            },
        },
        "accepted_animation": animation_link,
        "animation_candidates": _animation_candidates(event, source_width, source_height, recipe_matches, references, reel),
    }


def _direct_memberships(
    events: Mapping[str, Mapping[str, Any]], valid_identities: set[str]
) -> dict[frozenset[str], list[dict[str, Any]]]:
    observed_groups: dict[tuple[int, tuple[str, ...]], dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for identity, event in events.items():
        if identity not in valid_identities:
            continue
        for observation in event.get("observations") or []:
            composition = observation.get("composition") if isinstance(observation.get("composition"), Mapping) else {}
            raw_members = tuple(sorted(str(value) for value in composition.get("tracklet_ids") or []))
            if raw_members:
                observed_groups[(int(observation["frame_index"]), raw_members)][identity] = observation
    memberships: dict[frozenset[str], list[dict[str, Any]]] = defaultdict(list)
    for (frame_index, _), observations in observed_groups.items():
        members = frozenset(observations)
        if len(members) > 1:
            memberships[members].append({
                "analyzer_frame_index": frame_index,
                "timestamp_seconds": float(next(iter(observations.values()))["timestamp"]),
                "observations": observations,
            })
    return memberships


def _cross_group_simultaneity(
    events: Mapping[str, Mapping[str, Any]], valid_identities: set[str], source_fps: float, timeline_fps: float
) -> list[dict[str, Any]]:
    by_frame: dict[int, dict[str, tuple[tuple[str, ...], float]]] = defaultdict(dict)
    for identity, event in events.items():
        if identity not in valid_identities:
            continue
        for observation in event.get("observations") or []:
            composition = observation.get("composition") if isinstance(observation.get("composition"), Mapping) else {}
            raw_members = tuple(sorted(str(value) for value in composition.get("tracklet_ids") or []))
            by_frame[int(observation["frame_index"])][identity] = (raw_members, float(observation["timestamp"]))
    pair_frames: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
    for frame_index, rows in by_frame.items():
        for left, right in combinations(sorted(rows), 2):
            if rows[left][0] != rows[right][0]:
                pair_frames[(left, right)].append((frame_index, rows[left][1]))
    return [
        {
            "source_identity": pair[0],
            "target_identity": pair[1],
            "relationship_type": "CO_VISIBLE_DIFFERENT_OBSERVED_GROUPS",
            "supporting_analyzer_frame_indices": [frame for frame, _ in rows],
            "supporting_source_frames": [int(round(timestamp * source_fps)) for _, timestamp in rows],
            "supporting_timeline_frames": [int(round(timestamp * timeline_fps)) for _, timestamp in rows],
            "supporting_seconds": [timestamp for _, timestamp in rows],
            "authority": "SOURCE_OBSERVED_SAME_FRAME",
            "composition_membership_implied": False,
        }
        for pair, rows in sorted(pair_frames.items())
    ]


def _composition_window(
    identities: Sequence[str], events: Mapping[str, Mapping[str, Any]], review: Mapping[str, Any]
) -> tuple[float, float]:
    case = next((row for row in review.get("cases") or [] if set(row["identities"]) == set(identities)), None)
    if case:
        return tuple(float(value) for value in case["window_seconds"])
    return (
        min(float(events[identity]["start"]) for identity in identities),
        max(float(events[identity]["end"]) for identity in identities),
    )


def build(
    style: Mapping[str, Any], lifecycle: Mapping[str, Any], recipes: Mapping[str, Any], *, timeline_fps: float,
    video_id: str = "", review: Mapping[str, Any] | None = None,
    reference_style: Mapping[str, Any] | None = None, reference_recipes: Mapping[str, Any] | None = None,
    reference_style_path: Path | None = None,
) -> dict[str, Any]:
    source_fps = float((style.get("video_info") or {}).get("fps") or 0.0)
    source_width = float((style.get("video_info") or {}).get("width") or 0.0)
    source_height = float((style.get("video_info") or {}).get("height") or 0.0)
    if source_fps <= 0 or timeline_fps <= 0:
        raise ValueError("positive_source_and_timeline_fps_required")
    events = _event_index(style)
    lifecycle_tokens = _lifecycle_token_index(lifecycle)
    if not lifecycle_tokens:
        lifecycle_tokens = {
            identity: {
                "window": _window(float(event["start"]), float(event["end"]), timeline_fps),
                "window_authority": "CAPTION_STYLE_EVENT_FALLBACK",
            }
            for identity, event in events.items()
        }
    review = review or {}
    recipe_matches = _recipe_index(recipes)
    references = (_slide_references(reference_style, reference_recipes, reference_style_path)
                  if reference_style is not None and reference_recipes is not None and reference_style_path is not None else [])
    frame_results = style.get("frame_results") or []
    valid_identities = set(events) & set(lifecycle_tokens)
    direct_memberships = _direct_memberships(events, valid_identities)
    maximal_memberships = sorted(
        (
            members
            for members in direct_memberships
            if not any(members < other for other in direct_memberships)
        ),
        key=lambda members: tuple(sorted(members)),
    )
    memberships_per_identity = Counter(identity for members in maximal_memberships for identity in members)
    compositions = []
    composition_inputs: list[tuple[list[str], list[dict[str, Any]]]] = [
        (sorted(members), direct_memberships[members]) for members in maximal_memberships
    ]
    covered = set().union(*maximal_memberships) if maximal_memberships else set()
    composition_inputs.extend(([identity], []) for identity in sorted(valid_identities - covered))
    for identities, direct_evidence in composition_inputs:
        selected = set(identities)
        review_by_identity = {
            identity: _review_evidence(identity, review, source_fps, timeline_fps)
            for identity in identities
        }
        identity_rows = [
            {
                "identity": identity,
                "observations": [
                    {
                        "source_frame": int(round(float(row["timestamp_seconds"]) * source_fps)),
                        "bbox": row["observations"][identity]["bbox"],
                        "accepted": True,
                    }
                    for row in direct_evidence
                ],
            }
            for identity in identities
        ]
        hint = "direct:" + "__".join(identities)
        graph = build_composition_graph(identity_rows, {identity: hint for identity in identities})
        window_seconds = _composition_window(identities, events, review)
        states = _states(
            frame_results,
            identities,
            events,
            review_by_identity,
            source_fps,
            timeline_fps,
            window_seconds,
        )
        direct_co_visible_observations = [
            {
                "at_seconds": row["timestamp_seconds"],
                "source_frame": int(round(float(row["timestamp_seconds"]) * source_fps)),
                "timeline_frame": int(round(float(row["timestamp_seconds"]) * timeline_fps)),
                "analyzer_frame_index": row["analyzer_frame_index"],
                "member_identities": identities,
                "authority": "SOURCE_OBSERVED_SAME_FRAME_GROUP",
            }
            for row in direct_evidence
        ]
        directly_grouped_frames = {row["analyzer_frame_index"] for row in direct_co_visible_observations}
        for state in states:
            if (
                len(identities) == 1
                or
                set(state["observed_member_identities"]) != selected
                or state["analyzer_frame_index"] in directly_grouped_frames
            ):
                continue
            authorities = {row["authority"] for row in state["member_evidence"].values()}
            if "TARGETED_SOURCE_FRAME_REVIEW" not in authorities:
                continue
            direct_co_visible_observations.append({
                "at_seconds": state["at_seconds"],
                "source_frame": state["source_frame"],
                "timeline_frame": state["timeline_frame"],
                "analyzer_frame_index": state["analyzer_frame_index"],
                "member_identities": identities,
                "authority": "TARGETED_SOURCE_FRAME_REVIEW_WITH_OCR_SUPPORT",
            })
        direct_co_visible_observations.sort(key=lambda row: row["at_seconds"])
        co_visible = _co_visible_intervals(states, identities, source_fps, timeline_fps) if len(identities) > 1 else []
        graph_members = [row for row in graph["compositions"] if set(row["member_identities"]) == selected]
        if len(identities) > 1 and len(graph_members) != 1:
            raise ValueError(f"source_membership_not_proven:{identities}")
        members = [
            _member(
                identity,
                events[identity],
                lifecycle_tokens[identity],
                review_by_identity[identity],
                recipe_matches.get(str(events[identity].get("event_id") or ""), []),
                str(recipes.get("decision") or "UNSPECIFIED"),
                source_fps,
                timeline_fps,
                source_width,
                source_height,
                references,
                video_id,
            )
            for identity in identities
        ]
        composition = {
            "composition_id": "source_composition_" + "__".join(sorted(identities)),
            "kind": "multi_member" if len(identities) > 1 else "standalone",
            "visual_member_identities": identities,
            "membership_authority": graph_members[0]["authority"] if graph_members else "SOURCE_OBSERVED_STANDALONE",
            "members": members,
            "co_visible_intervals": co_visible,
            "direct_co_visible_observations": direct_co_visible_observations,
            "states": states,
            "spatial_relationships": graph["relationships"],
            "unresolved_relationships": [
                *([{
                    "relationship_type": "Z_ORDER",
                    "status": "unresolved",
                    "reason": "no_directional_occlusion_or_aligned_glyph_mask_evidence",
                }] if len(identities) > 1 else []),
                *[
                    {
                        "relationship_type": "EXIT_BEHAVIOR",
                        "visual_identity": member["visual_identity"],
                        "status": member["phases"]["exit"]["status"],
                        "reason": member["phases"]["exit"]["reason"],
                    }
                    for member in members
                ],
            ],
        }
        case = next((row for row in review.get("cases") or [] if set(row["identities"]) == selected), None)
        if case:
            composition["accepted_regression_case"] = case["name"]
        compositions.append(composition)
    unresolved_assignments = [
        {
            "visual_identity": identity,
            "candidate_composition_count": count,
            "status": "unresolved",
            "reason": "identity_has_multiple_distinct_direct_membership_sets; not_transitively_merged",
        }
        for identity, count in sorted(memberships_per_identity.items())
        if count > 1
    ]
    linked_animation_identities = {
        member["visual_identity"]
        for composition in compositions
        for member in composition["members"]
        if member["accepted_animation"]["status"] == "linked"
    }
    cross_group_simultaneity = _cross_group_simultaneity(events, valid_identities, source_fps, timeline_fps)
    return {
        "schema": "video_cloner.caption_compositions",
        "schema_version": 1,
        "reel": video_id or Path(str(style.get("video_path") or "unknown")).stem,
        "coordinate_spaces": {
            "source": {"fps": source_fps, "frame_rule": "round(observation_timestamp_seconds * source_fps)"},
            "timeline": {"fps": timeline_fps, "frame_rule": "round(observation_timestamp_seconds * timeline_fps)"},
            "analyzer_frame_index": "sample ordinal retained only as observation provenance; not a decoded source frame",
        },
        "authority_separation": {
            "membership_and_geometry": "SOURCE_OBSERVED",
            "retained_visibility": "INFERRED_ONLY_BETWEEN_POSITIVE_SOURCE_OBSERVATIONS",
            "ocr_omission": "UNKNOWN_UNLESS_TARGETED_SOURCE_FRAME_EVIDENCE_PROVES_PRESENCE_OR_ABSENCE",
            "semantic_reference": "TRANSCRIPT_ASSOCIATION",
            "animation_channels": "OPENCV_SOURCE_MEASUREMENT",
            "animation_acceptance": str(recipes.get("decision") or "UNSPECIFIED"),
        },
        "coverage": {
            "accepted_visual_identity_count": len(valid_identities),
            "covered_visual_identity_count": len({identity for row in compositions for identity in row["visual_member_identities"]}),
            "multi_member_composition_count": sum(row["kind"] == "multi_member" for row in compositions),
            "standalone_composition_count": sum(row["kind"] == "standalone" for row in compositions),
            "direct_membership_set_count_before_maximal_filter": len(direct_memberships),
            "unambiguous_animation_identity_count": len(linked_animation_identities),
            "cross_group_simultaneity_pair_count": len(cross_group_simultaneity),
        },
        "unresolved_identity_assignments": unresolved_assignments,
        "cross_group_simultaneity": cross_group_simultaneity,
        "compositions": compositions,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--style", type=Path, required=True)
    parser.add_argument("--lifecycle", type=Path)
    parser.add_argument("--recipes", type=Path)
    parser.add_argument("--video-id", default="")
    parser.add_argument("--review-evidence", type=Path)
    parser.add_argument("--reference-style", type=Path)
    parser.add_argument("--reference-recipes", type=Path)
    parser.add_argument("--timeline-fps", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (args.reference_style is None) != (args.reference_recipes is None):
        parser.error("reference style and recipes must be supplied together")
    if args.output.is_file():
        existing = _load(args.output)
        provenance = existing.get("provenance") if isinstance(existing.get("provenance"), Mapping) else {}
        expected = {"implementation": Path(__file__), "style": args.style, **({"lifecycle": args.lifecycle} if args.lifecycle else {}), **({"recipes": args.recipes} if args.recipes else {}), **({"review_evidence": args.review_evidence} if args.review_evidence else {}), **({"reference_style": args.reference_style, "reference_recipes": args.reference_recipes} if args.reference_style else {})}
        timeline = existing.get("coordinate_spaces", {}).get("timeline", {})
        if (existing.get("schema") == "video_cloner.caption_compositions"
                and float(timeline.get("fps") or 0.0) == args.timeline_fps
                and set(provenance) == set(expected)
                and all(isinstance(provenance.get(name), Mapping)
                        and provenance[name].get("sha256") == _sha256(path)
                        for name, path in expected.items())):
            print(json.dumps({"output": str(args.output), "status": "reused_hash_matched_authority"}, sort_keys=True))
            return 0
    result = build(
        _load(args.style),
        _load(args.lifecycle) if args.lifecycle else {},
        _load(args.recipes) if args.recipes else {},
        timeline_fps=args.timeline_fps,
        video_id=args.video_id,
        review=_load(args.review_evidence) if args.review_evidence else {},
        reference_style=_load(args.reference_style) if args.reference_style else None,
        reference_recipes=_load(args.reference_recipes) if args.reference_recipes else None,
        reference_style_path=args.reference_style,
    )
    result["provenance"] = {
        "implementation": {"path": str(Path(__file__)), "sha256": _sha256(Path(__file__))},
        "style": {"path": str(args.style), "sha256": _sha256(args.style)},
        **({"lifecycle": {"path": str(args.lifecycle), "sha256": _sha256(args.lifecycle)}} if args.lifecycle else {}),
        **({"recipes": {"path": str(args.recipes), "sha256": _sha256(args.recipes)}} if args.recipes else {}),
        **({"review_evidence": {"path": str(args.review_evidence), "sha256": _sha256(args.review_evidence)}} if args.review_evidence else {}),
        **({"reference_style": {"path": str(args.reference_style), "sha256": _sha256(args.reference_style)},
            "reference_recipes": {"path": str(args.reference_recipes), "sha256": _sha256(args.reference_recipes)}} if args.reference_style else {}),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "composition_count": len(result["compositions"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
