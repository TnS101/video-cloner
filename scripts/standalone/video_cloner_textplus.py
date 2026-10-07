from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path
from typing import Mapping, Sequence

from scripts.davinci import caption_animation_step_3C as animation_normalizer
from scripts.davinci import compile_davinci_textplus_fcpxml as canonical


REPORT_SCHEMA = "video_cloner.standalone_textplus.v1"


class StandaloneTextplusError(RuntimeError):
    pass


def _read(path: str | Path, label: str) -> tuple[Path, dict]:
    resolved = Path(path).expanduser().resolve()
    try:
        value = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise StandaloneTextplusError(f"missing or malformed {label}: {resolved}") from error
    if not isinstance(value, dict):
        raise StandaloneTextplusError(f"{label} must be a JSON object")
    return resolved, value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _source_cue_id(value: object) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return f"sub_{int(digits):03d}" if digits and int(digits) > 0 else ""


def _source_evidence(event: Mapping[str, object]) -> dict[str, object] | None:
    raw = event.get("raw") if isinstance(event.get("raw"), Mapping) else event
    observed_values = raw.get("observed_texts")
    if not isinstance(observed_values, list):
        return None
    observed = [canonical.norm_text(value) for value in observed_values if canonical.norm_text(value)]
    semantic = [canonical.normalize_semantic_caption_text(value) for value in observed]
    if len(semantic) < 2 or not semantic[0] or len(set(semantic)) != 1:
        return None
    selected = canonical.norm_text(raw.get("observed_text"))
    if canonical.normalize_semantic_caption_text(selected) != semantic[0]:
        return None
    confidence = raw.get("confidence") if isinstance(raw.get("confidence"), Mapping) else {}
    return {
        "event_id": str(raw.get("event_id") or event.get("id") or ""),
        "cue_id": _source_cue_id(raw.get("cue_id") or event.get("cue_id")),
        "observed_text": selected,
        "observed_texts": observed,
        "start": event.get("start"),
        "end": event.get("end"),
        "confidence": dict(confidence),
    }


def _event_proposal(
    event: Mapping[str, object],
    cues: Sequence[Mapping[str, object]],
    cue_index: int,
) -> dict[str, object] | None:
    evidence = _source_evidence(event)
    if evidence is None:
        return None
    observed = str(evidence["observed_text"])
    observed_semantic = canonical.normalize_semantic_caption_text(observed)
    transcript = canonical.norm_text(cues[cue_index].get("text"))
    transcript_semantic = canonical.normalize_semantic_caption_text(transcript)

    if observed_semantic == transcript_semantic:
        text = observed if observed.casefold() == transcript.casefold() else transcript
        return {
            "start": cue_index,
            "end": cue_index,
            "text": text,
            "decision": "source_exact",
            "evidence": evidence,
        }

    # A source composite is one visible token backed by adjacent semantic cues.
    if not any(character.isspace() for character in observed) or len(evidence["observed_texts"]) >= 4:
        combined = transcript_semantic
        for start in range(cue_index - 1, -1, -1):
            combined = canonical.normalize_semantic_caption_text(cues[start].get("text")) + combined
            if combined == observed_semantic:
                return {
                    "start": start,
                    "end": cue_index,
                    "text": observed,
                    "decision": "source_composite",
                    "evidence": evidence,
                }
            if len(combined) >= len(observed_semantic):
                break

    transcript_words = transcript.split()
    observed_words = observed.split()
    if (
        len(transcript_words) == len(observed_words) == 1
        and transcript_semantic.isalpha()
        and observed_semantic.isalpha()
        and SequenceMatcher(None, transcript_semantic, observed_semantic).ratio() >= 0.70
    ):
        return {
            "start": cue_index,
            "end": cue_index,
            "text": observed,
            "decision": "source_corrected",
            "evidence": evidence,
        }
    return None


def validate_caption_authority(
    cues: Sequence[Mapping[str, object]], source_ids: Sequence[str]
) -> dict[str, object]:
    expected = list(source_ids)
    position = {cue_id: index for index, cue_id in enumerate(expected)}
    if not expected or len(position) != len(expected) or any(not cue_id for cue_id in expected):
        raise StandaloneTextplusError("generic caption source IDs are empty or duplicated")
    flattened: list[str] = []
    authority_ids: list[str] = []
    for cue in cues:
        cue_id = str(cue.get("id") or "")
        coverage = cue.get("source_cue_ids")
        text = canonical.norm_text(cue.get("text"))
        if not cue_id or not text or not isinstance(coverage, list) or not coverage:
            raise StandaloneTextplusError("caption authority cue is malformed")
        covered = [str(value) for value in coverage]
        if any(value not in position for value in covered):
            raise StandaloneTextplusError("caption authority references an unknown source cue")
        reconciliation = cue.get("reconciliation")
        if not isinstance(reconciliation, Mapping):
            raise StandaloneTextplusError("caption authority reconciliation is missing")
        decision = str(reconciliation.get("decision") or "")
        if decision not in {"transcript_fallback", "source_exact", "source_corrected", "source_composite"}:
            raise StandaloneTextplusError("caption authority reconciliation decision is unsupported")
        evidence = reconciliation.get("evidence")
        if decision != "transcript_fallback" and (not isinstance(evidence, list) or not evidence):
            raise StandaloneTextplusError("caption authority semantic correction has no source evidence")
        if decision == "source_composite" and len(covered) < 2:
            raise StandaloneTextplusError("caption authority composite does not cover multiple source cues")
        if decision != "source_composite" and len(covered) != 1:
            raise StandaloneTextplusError("caption authority non-composite covers multiple source cues")
        if decision in {"source_exact", "source_corrected", "source_composite"}:
            observed = [row for row in evidence if isinstance(row, Mapping) and canonical.normalize_semantic_caption_text(row.get("observed_text")) == canonical.normalize_semantic_caption_text(text)]
            if not observed:
                raise StandaloneTextplusError("caption authority text is not supported by its source evidence")
        indexes = [position[value] for value in covered]
        if indexes != list(range(indexes[0], indexes[0] + len(indexes))):
            raise StandaloneTextplusError("caption authority many-to-one coverage is not adjacent")
        authority_ids.append(cue_id)
        flattened.extend(covered)
    if len(set(authority_ids)) != len(authority_ids):
        raise StandaloneTextplusError("caption authority IDs are duplicated")
    if flattened != expected:
        raise StandaloneTextplusError("caption authority source coverage is duplicated, dropped, or reordered")
    return {
        "source_cue_count": len(expected),
        "authority_cue_count": len(cues),
        "source_coverage_count": len(flattened),
        "source_coverage_exact": True,
    }


def derive_caption_authority(
    raw_cues: Sequence[Mapping[str, object]],
    style_data: Mapping[str, object],
    fps: float,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    source_ids = [str(cue.get("id") or "") for cue in raw_cues]
    by_id = {cue_id: index for index, cue_id in enumerate(source_ids)}
    proposals: dict[int, list[dict[str, object]]] = {}
    for event in canonical.extract_caption_style_events(dict(style_data), fps=fps):
        cue_id = _source_cue_id(event.get("cue_id"))
        if cue_id not in by_id:
            continue
        proposal = _event_proposal(event, raw_cues, by_id[cue_id])
        if proposal is not None:
            proposals.setdefault(int(proposal["start"]), []).append(proposal)

    authority: list[dict[str, object]] = []
    cursor = 0
    while cursor < len(raw_cues):
        candidates = proposals.get(cursor, [])
        distinct = {
            (int(row["end"]), str(row["text"]), str(row["decision"]))
            for row in candidates
        }
        selected = candidates[0] if len(distinct) == 1 else None
        end = int(selected["end"]) if selected is not None else cursor
        covered = source_ids[cursor : end + 1]
        first = raw_cues[cursor]
        last = raw_cues[end]
        cue = dict(first)
        cue.update({
            "id": covered[0],
            "index": len(authority) + 1,
            "text": str(selected["text"]) if selected is not None else canonical.norm_text(first.get("text")),
            "start": first.get("start"),
            "end": last.get("end"),
            "start_frame": first.get("start_frame"),
            "end_frame": last.get("end_frame"),
            "source_cue_ids": covered,
            "reconciliation": {
                "decision": str(selected["decision"]) if selected is not None else "transcript_fallback",
                "evidence": [selected["evidence"]] if selected is not None else [],
            },
        })
        raw = dict(first.get("raw") or {})
        raw["timeline_start_frame"] = cue["start_frame"]
        raw["timeline_end_frame"] = cue["end_frame"]
        cue["raw"] = raw
        cue["duration"] = round(float(cue["end"]) - float(cue["start"]), 6)
        cue["duration_frames"] = int(cue["end_frame"]) - int(cue["start_frame"])
        authority.append(cue)
        cursor = end + 1

    summary = validate_caption_authority(authority, source_ids)
    decisions: dict[str, int] = {}
    for cue in authority:
        decision = str((cue.get("reconciliation") or {}).get("decision"))
        decisions[decision] = decisions.get(decision, 0) + 1
    return authority, {
        "schema": "video_cloner.caption_authority.v1",
        "schema_version": 1,
        "summary": {**summary, "decision_counts": dict(sorted(decisions.items()))},
        "cues": authority,
    }


def _overlap_pairs(cues: Sequence[Mapping[str, object]]) -> int:
    ordered = sorted(cues, key=lambda cue: (int(cue["start_frame"]), int(cue["end_frame"])))
    return sum(
        1
        for index, left in enumerate(ordered)
        for right in ordered[index + 1 :]
        if int(right["start_frame"]) < int(left["end_frame"])
    )


def _authority_overlap_pairs(cues: Sequence[Mapping[str, object]], lifecycle: Mapping[str, object]) -> int:
    by_layer = {f"caption_layer_{cue['id']}": cue for cue in cues}
    pairs = lifecycle.get("visual_overlap_pairs")
    if not isinstance(pairs, list) or len({tuple(pair) for pair in pairs if isinstance(pair, list)}) != len(pairs):
        raise StandaloneTextplusError("caption lifecycle overlap authority is missing or duplicated")
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2 or pair[0] not in by_layer or pair[1] not in by_layer:
            raise StandaloneTextplusError("caption lifecycle overlap pair references an unknown cue")
        left, right = by_layer[pair[0]], by_layer[pair[1]]
        if int(left["start_frame"]) >= int(right["end_frame"]) or int(right["start_frame"]) >= int(left["end_frame"]):
            raise StandaloneTextplusError("caption lifecycle overlap pair is not present in emitted timing")
    expected = (lifecycle.get("summary") or {}).get("visual_concurrent_overlap_pair_count")
    if expected != len(pairs):
        raise StandaloneTextplusError("caption lifecycle overlap summary does not match its pair authority")
    return len(pairs)


def validate_caption_cues(cues: Sequence[Mapping[str, object]], expected_ids: Sequence[str]) -> dict[str, object]:
    ids = [str(cue.get("id") or "") for cue in cues]
    if ids != list(expected_ids) or len(set(ids)) != len(ids):
        raise StandaloneTextplusError("caption cue IDs/order/cardinality do not match caption authority")

    lane_intervals: dict[int, list[tuple[int, int]]] = {}
    for cue in cues:
        lane = int(cue.get("lane") or 1)
        lane_intervals.setdefault(lane, []).append((int(cue["start_frame"]), int(cue["end_frame"])))
    same_lane_overlaps = 0
    for intervals in lane_intervals.values():
        intervals.sort()
        same_lane_overlaps += sum(current[0] < previous[1] for previous, current in zip(intervals, intervals[1:]))
    if same_lane_overlaps:
        raise StandaloneTextplusError(f"same-lane caption overlaps: {same_lane_overlaps}")

    return {
        "semantic_cue_count": len(cues),
        "overlap_pair_count": _overlap_pairs(cues),
        "same_lane_overlap_count": same_lane_overlaps,
        "lane_usage": {str(lane): len(lane_intervals[lane]) for lane in sorted(lane_intervals)},
    }


def render_visual_compositions(
    compositions: Sequence[Mapping[str, object]], semantic_ids: Sequence[str], fps: float
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Adapt canonical visual tokens one-for-one into compiler cues."""
    expected = list(semantic_ids)
    expected_set = set(expected)
    composition_ids: set[str] = set()
    token_ids: set[str] = set()
    cues: list[dict[str, object]] = []
    unresolved: list[str] = []
    for composition in compositions:
        composition_id = str(composition.get("composition_id") or "")
        window = composition.get("window")
        authority = composition.get("authority")
        tokens = composition.get("tokens")
        if (
            not composition_id or composition_id in composition_ids
            or not isinstance(window, list) or len(window) != 2 or int(window[1]) <= int(window[0])
            or not isinstance(authority, Mapping) or authority.get("kind") not in {"visual_primary", "transcript_fallback", "unresolved"}
            or not isinstance(tokens, list) or not tokens
        ):
            raise StandaloneTextplusError("visual composition authority is malformed")
        composition_ids.add(composition_id)
        if authority["kind"] == "unresolved":
            unresolved.append(composition_id)
        for token in tokens:
            if not isinstance(token, Mapping):
                raise StandaloneTextplusError("visual composition token is malformed")
            token_id = str(token.get("token_id") or "")
            visual_identity = str(token.get("visual_event_identity") or "")
            token_window = token.get("window")
            token_semantic_ids = token.get("semantic_ids")
            text = canonical.norm_text(token.get("text"))
            if (
                not token_id or token_id in token_ids or not visual_identity or not text
                or not isinstance(token_window, list) or len(token_window) != 2
                or int(token_window[1]) <= int(token_window[0])
                or int(token_window[0]) < int(window[0]) or int(token_window[1]) > int(window[1])
                or not isinstance(token_semantic_ids, list)
            ):
                raise StandaloneTextplusError("visual composition token is malformed")
            token_ids.add(token_id)
            source_ids = [str(value) for value in token_semantic_ids]
            if len(source_ids) != len(set(source_ids)):
                raise StandaloneTextplusError("visual composition semantic references are duplicated")
            if any(value not in expected_set for value in source_ids):
                raise StandaloneTextplusError("visual composition semantic reference is unknown")
            start_frame, end_frame = [int(value) for value in token_window]
            cue = {
                "id": token_id,
                "index": len(cues) + 1,
                "text": text,
                "start_frame": start_frame,
                "end_frame": end_frame,
                "start": start_frame / fps,
                "end": end_frame / fps,
                "duration": (end_frame - start_frame) / fps,
                "duration_frames": end_frame - start_frame,
                "source_cue_ids": source_ids,
                "semantic_reference_ids": source_ids,
                "visual_composition_id": composition_id,
                "timing_authority": authority["kind"],
                "raw": {"timeline_start_frame": start_frame, "timeline_end_frame": end_frame},
            }
            if token.get("style_evidence_id"):
                cue["style_evidence_id"] = str(token["style_evidence_id"])
            if token.get("style_ref"):
                cue["style_ref"] = str(token["style_ref"])
            if token.get("visual_event_identity"):
                cue["visual_event_identity"] = visual_identity
            if token.get("accepted_motion_authority"):
                cue["accepted_motion_authority"] = dict(token["accepted_motion_authority"])
            if token.get("static_style"):
                cue["static_style"] = dict(token["static_style"])
            cues.append(cue)
    if unresolved:
        raise StandaloneTextplusError("unresolved visual composition authority: " + ",".join(unresolved))
    lane_allocation = canonical.allocate_caption_lanes(cues, base_lane=1)
    reference_ids = [
        semantic_id
        for cue in cues
        for semantic_id in cue.get("semantic_reference_ids") or []
    ]
    return cues, {
        "enabled": True,
        "composition_count": len(composition_ids),
        "render_token_count": len(cues),
        "semantic_reference_occurrence_count": sum(len(cue.get("semantic_reference_ids") or []) for cue in cues),
        "semantic_reference_distinct_count": len({value for cue in cues for value in cue.get("semantic_reference_ids") or []}),
        "semantic_coverage_exact": reference_ids == expected,
        "lane_allocation": lane_allocation,
    }


def resolve_visual_style_authority(
    cues: Sequence[dict[str, object]], style_data: Mapping[str, object], fps: float
) -> tuple[dict[int, dict[str, object]], int]:
    """Resolve canonical visual style pointers without timing/text rematching."""
    events = canonical.extract_caption_style_events(dict(style_data), fps=fps)
    by_id: dict[str, dict[str, object]] = {}
    for event in events:
        event_id = str(event.get("id") or "")
        if not event_id:
            continue
        if event_id in by_id:
            raise StandaloneTextplusError(f"visual style evidence ID is duplicated: {event_id}")
        by_id[event_id] = event
    styles: dict[int, dict[str, object]] = {}
    for cue in cues:
        evidence_id = str(cue.get("style_evidence_id") or "")
        if not evidence_id:
            continue
        event = by_id.get(evidence_id)
        raw = event.get("raw") if isinstance(event, Mapping) and isinstance(event.get("raw"), Mapping) else {}
        match = raw.get("match") if isinstance(raw.get("match"), Mapping) else {}
        anchor = raw.get("placement", {}).get("anchor") if isinstance(raw.get("placement"), Mapping) else None
        source_ids = {
            _source_cue_id(value)
            for value in (cue.get("source_cue_ids") or cue.get("semantic_reference_ids") or [])
        }
        event_raw = event.get("raw") if isinstance(event, Mapping) and isinstance(event.get("raw"), Mapping) else {}
        identity_matches = bool(
            not source_ids
            and cue.get("visual_event_identity")
            and str(event.get("visual_event_identity") or event_raw.get("visual_event_identity") or "")
            == str(cue.get("visual_event_identity"))
        )
        if (
            not event
            or match.get("reason") != "accepted"
            or (_source_cue_id(event.get("cue_id")) not in source_ids and not identity_matches)
            or not isinstance(anchor, Mapping)
            or not isinstance(anchor.get("x"), (int, float))
            or not isinstance(anchor.get("y"), (int, float))
        ):
            raise StandaloneTextplusError(f"visual style evidence is missing or unaccepted: {evidence_id}")
        contract = canonical.build_event_style_contract(dict(style_data), dict(event), overrides={})
        alignment = str((raw.get("placement") or {}).get("horizontal_align") or "").lower()
        contract["alignment"] = alignment if alignment in {"left", "center", "right"} else "center"
        font_family = str((raw.get("typography") or {}).get("font_family") or "").lower()
        unresolved = ["static_scale", "glow", "semantic_emphasis"]
        if font_family in {"", "unknown", "normal_or_unknown", "unknown_or_static_from_sampling"}:
            unresolved.insert(0, "font_family")
            contract["font_family_authority"] = "unresolved"
            contract["renderer_font_fallback"] = contract["font_name"]
        else:
            contract["font_family_authority"] = "visual_observed"
        contract["unresolved_style_properties"] = unresolved
        contract["style_authority"] = "visual_observed"
        contract["style_evidence_id"] = evidence_id
        video_info = style_data.get("video_info") if isinstance(style_data.get("video_info"), Mapping) else {}
        _ensure_textplus_size(contract, video_info.get("width"))
        index = int(cue.get("index") or 0)
        if index <= 0:
            raise StandaloneTextplusError("visual style cue index is invalid")
        cue["position_mode"] = "detected_fcpx"
        styles[index] = contract
    return styles, len(styles)


def _ensure_textplus_size(contract: dict[str, object], frame_width: object) -> None:
    current = contract.get("textplus_size")
    if isinstance(current, (int, float)) and not isinstance(current, bool) and current > 0:
        return
    font_size_px = contract.get("font_size_px")
    if (
        not isinstance(frame_width, (int, float)) or isinstance(frame_width, bool) or frame_width <= 0
        or not isinstance(font_size_px, (int, float)) or isinstance(font_size_px, bool) or font_size_px <= 0
    ):
        raise StandaloneTextplusError("TextPlus Size contract requires positive frame width and font size")
    contract["textplus_size"] = max(0.02, float(font_size_px) / float(frame_width) * 1.5)


def apply_static_style_authority(
    cues: Sequence[dict[str, object]], styles: Mapping[int, dict[str, object]], frame_width: object
) -> int:
    """Apply bounded source-backed static overrides without changing visual identities."""
    applied = 0
    static_lane_base = max((int(cue.get("lane") or 1) for cue in cues), default=1) + 1
    for cue in cues:
        raw = cue.get("static_style")
        if not isinstance(raw, Mapping):
            continue
        style = styles[int(cue["index"])]
        if raw.get("font_name"):
            style["font_name"] = str(raw["font_name"])
            style["font_family_authority"] = str(raw.get("font_authority") or "BEST_AVAILABLE_FONT_MATCH")
        if isinstance(raw.get("bold"), bool):
            style["bold"] = raw["bold"]
        if isinstance(raw.get("font_size_px"), (int, float)) and float(raw["font_size_px"]) > 0:
            style["font_size_px"] = int(round(float(raw["font_size_px"])))
            style.pop("textplus_size", None)
            _ensure_textplus_size(style, frame_width)
        bbox = raw.get("normalized_bbox")
        if isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox):
            placement = dict(style.get("placement") or {})
            placement["normalized_bbox"] = [float(v) for v in bbox]
            placement["anchor"] = {
                "x": (float(bbox[0]) + float(bbox[2])) / 2,
                "y": (float(bbox[1]) + float(bbox[3])) / 2,
                "coordinate_space": "normalized_frame",
            }
            style["placement"] = placement
            style["anchor"] = {"x": placement["anchor"]["x"], "y": placement["anchor"]["y"]}
        if raw.get("fill"):
            style["fill"] = str(raw["fill"])
        opacity = float(raw.get("fill_opacity", 1.0))
        style["fill_opacity"] = max(0.0, min(1.0, opacity))
        style["fill_fcpxml"] = canonical.rgb01_to_fcpxml(
            canonical.hex_to_rgb01(style["fill"]), style["fill_opacity"]
        )
        if raw.get("stroke_color"):
            style["outline"] = str(raw["stroke_color"])
        if isinstance(raw.get("stroke_width_px"), (int, float)):
            style["outline_px"] = max(0.0, float(raw["stroke_width_px"]))
        if raw.get("stroke_enabled") is False:
            style["outline_px"] = 0.0
        style["outline_fcpxml"] = canonical.rgb01_to_fcpxml(canonical.hex_to_rgb01(style["outline"]), 1.0)
        style["static_rotation_degrees"] = float(raw.get("static_rotation_degrees", 0.0))
        if isinstance(raw.get("static_z_order"), int) and int(raw["static_z_order"]) >= 0:
            cue["static_z_order"] = int(raw["static_z_order"])
            cue["lane"] = static_lane_base + int(raw["static_z_order"])
        applied += 1
    return applied


def attach_independent_style_evidence_contract(
    cues: Sequence[dict[str, object]], styles: Mapping[int, dict[str, object]]
) -> None:
    """Make per-identity style ownership explicit; physical fragments only share evidence."""
    for cue in cues:
        identity = str(cue.get("visual_event_identity") or cue.get("id") or "")
        style = styles[int(cue["index"])]
        cue["style_evidence_owner"] = identity
        style["style_evidence_owner"] = identity
        style["style_sharing_authority"] = "independent_by_default"
        fragment_group = (cue.get("static_style") or {}).get("fragment_group")
        if fragment_group:
            cue["physical_word_group_id"] = str(fragment_group)
            style["joint_physical_word_evidence"] = str(fragment_group)


def attach_visual_animation_authority(
    cues: Sequence[dict[str, object]],
    style_data: Mapping[str, object],
    visual_styles: Mapping[int, Mapping[str, object]],
    fps: float,
) -> int:
    """Attach normalized motion only to directly authorized visual tokens."""
    raw_events = style_data.get("caption_style_events")
    raw_id_counts: dict[str, int] = {}
    raw_visual_identity_counts: dict[str, int] = {}
    if isinstance(raw_events, list):
        for raw_event in raw_events:
            if isinstance(raw_event, Mapping):
                event_id = str(raw_event.get("event_id") or "")
                if event_id:
                    raw_id_counts[event_id] = raw_id_counts.get(event_id, 0) + 1
                visual_identity = str(raw_event.get("visual_event_identity") or "")
                if visual_identity:
                    raw_visual_identity_counts[visual_identity] = raw_visual_identity_counts.get(visual_identity, 0) + 1
    events: dict[str, list[dict[str, object]]] = {}
    events_by_visual_identity: dict[str, list[dict[str, object]]] = {}
    for event in canonical.extract_caption_style_events(dict(style_data), fps=fps):
        event_id = str(event.get("id") or "")
        if event_id:
            events.setdefault(event_id, []).append(event)
        raw = event.get("raw") if isinstance(event.get("raw"), Mapping) else {}
        visual_identity = str(raw.get("visual_event_identity") or "")
        if visual_identity:
            events_by_visual_identity.setdefault(visual_identity, []).append(event)

    explicit_only = any(isinstance(cue.get("accepted_motion_authority"), Mapping) for cue in cues)
    attached = 0
    for cue in cues:
        accepted = cue.get("accepted_motion_authority")
        if explicit_only and not isinstance(accepted, Mapping):
            continue
        index = int(cue.get("index") or 0)
        style = visual_styles.get(index)
        evidence_id = str(cue.get("style_evidence_id") or "")
        accepted_visual_identity = str(accepted.get("source_visual_event_identity") or "") if isinstance(accepted, Mapping) else ""
        if accepted_visual_identity:
            candidates = events_by_visual_identity.get(accepted_visual_identity, [])
            evidence_count = raw_visual_identity_counts.get(accepted_visual_identity, 0)
        else:
            candidates = events.get(evidence_id, [])
            evidence_count = raw_id_counts.get(evidence_id, 0)
        if (
            (not accepted_visual_identity and not evidence_id)
            or evidence_count != 1
            or not isinstance(style, Mapping)
            or style.get("style_authority") != "visual_observed"
            or len(candidates) != 1
        ):
            if isinstance(accepted, Mapping):
                raise StandaloneTextplusError("accepted motion style evidence is missing or ambiguous")
            continue

        event = candidates[0]
        evidence_id = str(event.get("id") or evidence_id)
        raw = event.get("raw") if isinstance(event.get("raw"), Mapping) else {}
        match = raw.get("match") if isinstance(raw.get("match"), Mapping) else {}
        source_ids = {
            _source_cue_id(value)
            for value in (cue.get("source_cue_ids") or cue.get("semantic_reference_ids") or [])
        }
        if (
            match.get("reason") != "accepted"
            or _source_cue_id(event.get("cue_id")) not in source_ids
        ):
            if isinstance(accepted, Mapping):
                raise StandaloneTextplusError("accepted motion does not match current visual evidence")
            continue

        duration_frames = int(cue.get("duration_frames") or 0)
        base_size = style.get("textplus_size")
        if isinstance(accepted, Mapping):
            keyframes = accepted.get("keyframes")
            if (
                accepted.get("authority") != "visual_observed"
                or (
                    accepted_visual_identity
                    and (
                        str(cue.get("visual_event_identity") or "") != accepted_visual_identity
                        or str(raw.get("visual_event_identity") or "") != accepted_visual_identity
                    )
                )
                or (not accepted_visual_identity and accepted.get("source_evidence_id") != evidence_id)
                or accepted.get("source_type") != "scale"
                or accepted.get("property") != "Size"
                or not isinstance(base_size, (int, float))
                or isinstance(base_size, bool)
                or base_size <= 0
                or not isinstance(keyframes, list)
                or len(keyframes) != 2
                or [int(row.get("frame", -1)) for row in keyframes if isinstance(row, Mapping)]
                != [0, duration_frames - 1]
                or [float(row.get("relative_time", -1)) for row in keyframes if isinstance(row, Mapping)]
                != [0.0, 1.0]
                or any(
                    not isinstance(row.get("value"), (int, float))
                    or isinstance(row.get("value"), bool)
                    or float(row["value"]) <= 0
                    for row in keyframes
                    if isinstance(row, Mapping)
                )
            ):
                raise StandaloneTextplusError("accepted motion authority is invalid")
            cue["animation_authority"] = {
                "authority": "visual_observed",
                "source_evidence_id": evidence_id,
                "source_type": "scale",
                "property": "Size",
                "keyframes": [
                    {
                        "frame": int(keyframe["frame"]),
                        "relative_time": float(keyframe["relative_time"]),
                        "value": float(keyframe["value"]),
                    }
                    for keyframe in keyframes
                ],
            }
            if accepted_visual_identity:
                cue["animation_authority"]["source_visual_event_identity"] = accepted_visual_identity
            attached += 1
            continue

        if not isinstance(raw.get("animation"), Mapping) or raw["animation"].get("detected") is not True:
            continue
        normalized, _failure = animation_normalizer.normalize_animation_event(
            dict(raw), {"duration_frames": duration_frames, "base_size": 1.0}
        )
        if not normalized or normalized.get("animation_type") not in {"slide", "scale"}:
            continue

        property_name = "Center" if normalized["animation_type"] == "slide" else "Size"
        value_name = "center_offset" if property_name == "Center" else "size_multiplier"
        if property_name == "Size" and (
            not isinstance(base_size, (int, float)) or isinstance(base_size, bool) or base_size <= 0
        ):
            continue
        keyframes = [
            {
                "frame": int(keyframe["frame"]),
                "relative_time": float(keyframe["relative_time"]),
                "value": (
                    keyframe[value_name]
                    if property_name == "Center"
                    else float(base_size) * float(keyframe[value_name])
                ),
            }
            for keyframe in normalized.get("keyframes", [])
            if 0 <= int(keyframe.get("frame", -1)) < duration_frames and value_name in keyframe
        ]
        if len(keyframes) != int(normalized.get("target_keyframe_count") or 0):
            continue

        cue["animation_authority"] = {
            "authority": "visual_observed",
            "source_evidence_id": evidence_id,
            "source_type": normalized["animation_type"],
            "property": property_name,
            "keyframes": keyframes,
        }
        attached += 1
    return attached


def prepare_textplus_authority(
    generic: Mapping[str, object],
    style_data: Mapping[str, object],
    lifecycle: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if generic.get("success") is not True or generic.get("schema") != "generic_edit_commands":
        raise StandaloneTextplusError("generic command authority is invalid")
    fps = canonical.extract_fps(dict(generic), fallback=24.0)
    raw_cues, source_info = canonical.extract_subtitle_cues(dict(generic), source="subtitle_clips", fps=fps)
    generic_ids = [str(row.get("subtitle_id") or "") for row in generic.get("subtitle_clips", []) if isinstance(row, dict)]
    if len(raw_cues) != len(generic_ids) or not raw_cues:
        raise StandaloneTextplusError("generic captions are missing or malformed")
    base_cues = canonical.enforce_timing_rules(raw_cues, fps=fps, min_duration_frames=1, prevent_overlap=True)
    authority_cues, caption_authority = derive_caption_authority(base_cues, style_data, fps)
    expected_ids = [str(row["id"]) for row in authority_cues]
    cues = canonical.enforce_timing_rules(authority_cues, fps=fps, min_duration_frames=1, prevent_overlap=True)

    lifecycle_info: dict[str, object] = {"enabled": False}
    overlap_pair_count = 0
    if lifecycle is not None:
        try:
            cues, lifecycle_info = canonical.apply_caption_lifecycle_plan(cues, dict(lifecycle), fps=fps, base_lane=1)
        except ValueError as error:
            raise StandaloneTextplusError(str(error)) from error
        overlap_pair_count = _authority_overlap_pairs(cues, lifecycle)
        compositions = lifecycle.get("visual_compositions")
        if compositions is not None:
            if not isinstance(compositions, list):
                raise StandaloneTextplusError("visual composition authority must be a list")
            semantic_cues = list(cues)
            visual_cues, visual_info = render_visual_compositions(compositions, generic_ids, fps)
            referenced = {
                semantic_id
                for cue in visual_cues
                for semantic_id in cue.get("semantic_reference_ids") or []
            }
            absent_ids: list[str] = []
            for semantic_cue in semantic_cues:
                source_ids = [str(value) for value in semantic_cue.get("source_cue_ids") or []]
                timing_authority = str(semantic_cue.get("timing_authority") or "")
                for semantic_id in source_ids:
                    if semantic_id in referenced:
                        continue
                    absent_ids.append(semantic_id)
                    if timing_authority != "transcript_fallback":
                        raise StandaloneTextplusError(
                            "semantic fallback disposition is unresolved: " + semantic_id
                        )
            for cue in visual_cues:
                cue["source_cue_ids"] = []
            cues = sorted(
                visual_cues,
                key=lambda cue: (
                    int(cue.get("start_frame") or 0),
                    int(cue.get("end_frame") or 0),
                    str(cue.get("id") or ""),
                ),
            )
            semantic_execution_ids = [
                semantic_id for semantic_id in generic_ids if semantic_id in referenced or semantic_id in absent_ids
            ]
            if semantic_execution_ids != generic_ids:
                raise StandaloneTextplusError("semantic ledger order/cardinality changed")
            canonical.allocate_caption_lanes(cues, base_lane=1)
            lifecycle_info = {
                **lifecycle_info,
                "visual_compositions": visual_info,
                "semantic_ledger": {
                    "ids": list(generic_ids),
                    "count": len(generic_ids),
                    "exactly_once": True,
                    "visual_reference_occurrence_count": visual_info["semantic_reference_occurrence_count"],
                    "visual_reference_distinct_count": visual_info["semantic_reference_distinct_count"],
                    "fallback_count": len(absent_ids),
                    "fallback_ids": absent_ids,
                },
            }
            expected_ids = [str(cue["id"]) for cue in cues]

    metrics = validate_caption_cues(cues, expected_ids)
    metrics["all_interval_overlap_pair_count"] = metrics.pop("overlap_pair_count")
    metrics["overlap_pair_count"] = overlap_pair_count
    if lifecycle_info.get("visual_compositions"):
        metrics.update(lifecycle_info["visual_compositions"])
    if lifecycle_info.get("semantic_ledger"):
        metrics.update({
            "semantic_ledger_count": lifecycle_info["semantic_ledger"]["count"],
            "semantic_ledger_exactly_once": lifecycle_info["semantic_ledger"]["exactly_once"],
            "semantic_fallback_count": lifecycle_info["semantic_ledger"]["fallback_count"],
        })
    source_text = {str(cue.get("id")): canonical.norm_text(cue.get("text")) for cue in raw_cues}
    casing_differences = [
        {"cue_id": coverage[0], "generic": source_text[coverage[0]], "output": output}
        for cue in cues
        for coverage in [list(cue.get("source_cue_ids") or [])]
        for output in [canonical.norm_text(cue.get("text"))]
        if (
            len(coverage) == 1
            and source_text[coverage[0]] != output
            and canonical.normalize_semantic_caption_text(source_text[coverage[0]])
            == canonical.normalize_semantic_caption_text(output)
        )
    ]
    metrics.update({
        "dropped_semantic_words": 0,
        "added_semantic_words": 0,
        "casing_difference_count": len(casing_differences),
        "casing_differences": casing_differences,
        "lifecycle_timing_change_count": int(lifecycle_info.get("lifecycle_differs_from_transcript_count", 0)),
    })

    effective_style_data = dict(style_data)
    recovery_events = lifecycle.get("source_visible_recovery_events") if lifecycle else None
    if recovery_events:
        if not isinstance(recovery_events, list) or not all(isinstance(row, Mapping) for row in recovery_events):
            raise StandaloneTextplusError("source-visible recovery style evidence is malformed")
        effective_style_data["caption_style_events"] = [
            *(style_data.get("caption_style_events") or []),
            *recovery_events,
        ]
    style = canonical.extract_style_contract(effective_style_data, profile_id="primary", overrides={})
    direct_styles, direct_style_count = resolve_visual_style_authority(cues, effective_style_data, fps)
    animation_authority_count = attach_visual_animation_authority(cues, effective_style_data, direct_styles, fps)
    heuristic_styles, style_info = canonical.assign_style_events_to_cues(
        [cue for cue in cues if int(cue.get("index") or 0) not in direct_styles],
        effective_style_data, style, {}, fps, enabled=True, match_window_sec=1.25, min_match_score=0.12
    )
    cue_styles = {**heuristic_styles, **direct_styles}
    video_info = style_data.get("video_info") if isinstance(style_data.get("video_info"), Mapping) else {}
    static_style_count = apply_static_style_authority(cues, cue_styles, video_info.get("width"))
    attach_independent_style_evidence_contract(cues, cue_styles)
    for contract in [style, *cue_styles.values()]:
        _ensure_textplus_size(contract, video_info.get("width"))
    return {
        "fps": fps,
        "cues": cues,
        "style": style,
        "cue_styles": cue_styles,
        "caption_source": source_info,
        "caption_authority": caption_authority,
        "caption_lifecycle": lifecycle_info,
        "visual_compositions": lifecycle.get("visual_compositions") if lifecycle else None,
        "caption_metrics": metrics,
        "style_event_matches": int(style_info.get("matched_cue_count", 0)) + direct_style_count,
        "animation_authority_count": animation_authority_count,
        "static_style_authority_count": static_style_count,
    }


def compile_textplus(
    generic_path: str | Path,
    caption_style_path: str | Path,
    output_fcpxml: str | Path,
    report_path: str | Path,
    lifecycle_path: str | Path | None = None,
    timeline_name: str | None = None,
) -> dict[str, object]:
    generic_file, generic = _read(generic_path, "generic commands")
    style_file, style_data = _read(caption_style_path, "caption style")
    lifecycle_file: Path | None = None
    lifecycle: dict | None = None
    if lifecycle_path is not None:
        lifecycle_file, lifecycle = _read(lifecycle_path, "caption lifecycle authority")
    prepared = prepare_textplus_authority(generic, style_data, lifecycle)
    fps = float(prepared["fps"])
    cues = prepared["cues"]
    style = prepared["style"]
    cue_styles = prepared["cue_styles"]
    name = timeline_name or f"{generic.get('video_id', generic_file.stem)}_standalone_textplus"
    xml = canonical.build_caption_only_fcpxml(
        cues, style, cue_styles, fps, 1080, 1920, name, "VC Caption", "1.10",
        canonical.DEFAULT_BASIC_TITLE_UID, 1, "reset", 0.0, 0.0,
    )
    xml_bytes = xml.encode("utf-8")
    root = ET.fromstring(xml_bytes)
    titles = root.findall(".//title")
    if len(titles) != len(cues):
        raise StandaloneTextplusError("canonical Text+ output dropped captions")

    output = Path(output_fcpxml).expanduser().resolve()
    report_file = Path(report_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(xml_bytes)
    report: dict[str, object] = {
        "schema": REPORT_SCHEMA,
        "success": True,
        "video_id": generic.get("video_id"),
        "inputs": {
            "generic": str(generic_file),
            "generic_sha256": _sha256_bytes(generic_file.read_bytes()),
            "caption_style": str(style_file),
            "caption_style_sha256": _sha256_bytes(style_file.read_bytes()),
            "caption_lifecycle": str(lifecycle_file) if lifecycle_file else None,
            "caption_lifecycle_sha256": _sha256_bytes(lifecycle_file.read_bytes()) if lifecycle_file else None,
        },
        "caption_source": prepared["caption_source"],
        "caption_authority": prepared["caption_authority"],
        "caption_lifecycle": prepared["caption_lifecycle"],
        "visual_compositions": prepared["visual_compositions"],
        "caption_metrics": prepared["caption_metrics"],
        "style_event_matches": prepared["style_event_matches"],
        "animation_authority_count": prepared["animation_authority_count"],
        "output": {"fcpxml": str(output), "sha256": _sha256_bytes(xml_bytes), "title_count": len(titles)},
        "canonical_textplus_compiler": str(Path(canonical.__file__).resolve()),
        "edit_operations_compiled": False,
        "resolve_invoked": False,
        "timeline_mutated": False,
        "save_project_invoked": False,
    }
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile standalone editable Text+ captions without edit operations or Resolve.")
    parser.add_argument("--generic", required=True)
    parser.add_argument("--caption-style", required=True)
    parser.add_argument("--caption-lifecycle-plan")
    parser.add_argument("--output-fcpxml", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--timeline-name")
    args = parser.parse_args(argv)
    try:
        report = compile_textplus(
            args.generic, args.caption_style, args.output_fcpxml, args.report,
            args.caption_lifecycle_plan, args.timeline_name,
        )
    except StandaloneTextplusError as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
