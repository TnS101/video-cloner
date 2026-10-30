from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path
from typing import Mapping, Sequence

from scripts.davinci import caption_animation_step_3C as animation_normalizer
from video_cloner.resolve import fcpxml as canonical


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
    compositions: Sequence[Mapping[str, object]], semantic_ids: Sequence[str], fps: float,
    style_data: Mapping[str, object] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Adapt canonical visual tokens one-for-one into compiler cues."""
    expected = list(semantic_ids)
    expected_set = set(expected)
    composition_ids: set[str] = set()
    token_ids: set[str] = set()
    cues: list[dict[str, object]] = []
    unresolved: list[str] = []
    omitted_segment_echoes: list[str] = []
    events = {
        str(event.get("event_id")): event
        for event in (style_data or {}).get("caption_style_events", [])
        if isinstance(event, Mapping) and event.get("event_id")
    }
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
            # Some accepted OCR tracklets are actually full transcript SEGMENTS
            # attached to a few frames, not observed word-level captions. They
            # have no word identity, repeat the segment verbatim, and must not
            # become independently visible titles.
            reference = token.get("semantic_reference")
            if not source_ids and isinstance(reference, Mapping):
                event = events.get(str(token.get("style_evidence_id") or ""), {})
                observed = [canonical.norm_text(row.get("text")) for row in event.get("observations") or []
                            if isinstance(row, Mapping)]
                phrase = canonical.norm_text(event.get("observed_text"))
                phrase_words = phrase.casefold().split()
                if (len(phrase_words) >= 2 and len(phrase_words) < len(text.split())
                        and phrase_words == text.casefold().split()[:len(phrase_words)]
                        and sum(value.casefold() == phrase.casefold() for value in observed) >= 3):
                    text = phrase
                reference_text = canonical.norm_text(reference.get("cue_text"))
                try:
                    reference_frames = round(
                        (float(reference["cue_end"]) - float(reference["cue_start"])) * fps
                    )
                except (KeyError, TypeError, ValueError):
                    reference_frames = 0
                if (
                    reference.get("label_source") == "transcript_cue"
                    and len(text.split()) >= 3
                    and text.casefold() == reference_text.casefold()
                    and reference_frames >= 2 * (end_frame - start_frame)
                ):
                    omitted_segment_echoes.append(token_id)
                    continue
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
        "omitted_segment_echo_ids": omitted_segment_echoes,
        "semantic_reference_occurrence_count": sum(len(cue.get("semantic_reference_ids") or []) for cue in cues),
        "semantic_reference_distinct_count": len({value for cue in cues for value in cue.get("semantic_reference_ids") or []}),
        "semantic_coverage_exact": reference_ids == expected,
        "lane_allocation": lane_allocation,
    }


def _prefer_source_visible_phrases(
    cues: list[dict[str, object]], style_data: Mapping[str, object], fps: float,
) -> tuple[list[dict[str, object]], list[str]]:
    """Use an actually observed full-screen phrase over transcript-only words.

    Only a direct OCR phrase with repeated exact source observations can own
    the display. Source-backed independent words/compositions are never
    replaced. A tracklet's OCR text switch is an exit, not persistence.
    """
    import re

    def words(value: object) -> list[str]:
        return re.findall(r"\w+(?:['’]\w+)*", str(value or "").casefold())

    observations: dict[str, list[tuple[float, str]]] = {}
    for group in style_data.get("caption_groups", []):
        if not isinstance(group, Mapping):
            continue
        try:
            timestamp = float(group["timestamp"])
        except (KeyError, ValueError, TypeError):
            continue
        for identity in group.get("tracklet_ids") or []:
            observations.setdefault(str(identity), []).append((timestamp, str(group.get("text") or "")))
    for rows in observations.values():
        rows.sort()

    remaining = list(cues)
    promoted: list[str] = []
    for phrase in list(cues):
        if (phrase.get("timing_authority") != "visual_primary"
                or phrase.get("semantic_reference_ids") or phrase.get("source_cue_ids")
                or not phrase.get("style_evidence_id")):
            continue
        target = words(phrase.get("text"))
        if len(target) < 2:
            continue
        identity = str(phrase.get("visual_event_identity") or "")
        samples = observations.get(identity, [])
        # Require >=3 independent source-frame detections of the COMPLETE
        # phrase. Partial OCR and transcript-cue aliases do not count.
        positive = [(t, text) for t, text in samples if words(text) == target]
        if len(positive) < 3:
            continue
        first, last = positive[0][0], positive[-1][0]
        if last - first < 0.15:
            continue
        # First directly observed replacement text, if any, bounds exit.
        changes = [t for t, text in samples if t > last and words(text) != target]
        observed_end = min(changes) if changes else last + 0.1
        first_frame = max(int(phrase["start_frame"]), int(round(first * fps)))
        last_frame = min(int(phrase["end_frame"]), max(first_frame + 1, int(round(observed_end * fps))))
        if last_frame <= first_frame:
            continue

        # Only consume the exact ordered transcript-only word sequence. If
        # even one word has its own source identity, keep that composition.
        near = sorted((cue for cue in remaining if cue is not phrase
                       and cue.get("timing_authority") == "transcript_fallback"
                       and len(cue.get("semantic_reference_ids") or cue.get("source_cue_ids") or []) == 1
                       and first_frame - 3 <= int(cue["start_frame"]) < last_frame
                       and int(cue["end_frame"]) <= last_frame + 3
                       and len(words(cue.get("text"))) == 1),
                      key=lambda row: (int(row["start_frame"]), int(row["end_frame"])))
        matches: list[dict[str, object]] = []
        for word_cue in near:
            if len(matches) == len(target):
                break
            if words(word_cue.get("text"))[0] == target[len(matches)]:
                if not matches and abs(int(word_cue["start_frame"]) - first_frame) > 4:
                    continue
                matches.append(word_cue)
            elif matches:
                break
        if len(matches) != len(target):
            continue
        ids = [str((cue.get("semantic_reference_ids") or cue.get("source_cue_ids"))[0]) for cue in matches]
        # The matched transcript IDs must not already be owned by independent
        # source-backed objects elsewhere in the same visual composition.
        if any(any(i in (other.get("semantic_reference_ids") or [])
                   for other in remaining if other is not phrase and other not in matches)
               for i in ids):
            continue
        phrase["start_frame"], phrase["end_frame"] = first_frame, last_frame
        phrase["start"], phrase["end"] = first_frame / fps, last_frame / fps
        phrase["duration_frames"] = last_frame - first_frame
        phrase["duration"] = (last_frame - first_frame) / fps
        phrase["raw"] = {"timeline_start_frame": first_frame, "timeline_end_frame": last_frame}
        phrase["semantic_reference_ids"] = ids
        phrase["source_cue_ids"] = list(ids)
        for word_cue in matches:
            remaining.remove(word_cue)
        promoted.append(str(phrase["id"]))
    return remaining, promoted


def _project_observed_phrase_states(
    cues: list[dict[str, object]],
    style_data: Mapping[str, object],
    generic: Mapping[str, object],
    fps: float,
) -> tuple[list[dict[str, object]], list[str]]:
    """Use repeated source OCR text states, not a word's transcript length.

    A tracked visual region can change from 'listen' to 'listen to'. Only
    promote the longer state when independent frames show it and its words
    match consecutive transcript semantics. Keep independently styled visual
    regions separate.
    """
    import re

    def words(value: object) -> list[str]:
        return re.findall(r"\w+(?:['’]\w+)*", str(value or "").casefold())

    transcript = [row for row in generic.get("subtitle_clips", []) if isinstance(row, Mapping)]
    transcript_ids = [str(row.get("subtitle_id") or "") for row in transcript]
    transcript_words = [words(row.get("text")) for row in transcript]
    positions = {value: i for i, value in enumerate(transcript_ids)}
    events = {
        str(row.get("visual_event_identity") or ""): row
        for row in style_data.get("caption_style_events", [])
        if isinstance(row, Mapping) and row.get("visual_event_identity")
    }
    # Reconciliation may keep a short, literal OCR word and discard a
    # simultaneous alias that later becomes a source-visible phrase. Its
    # observations remain valid evidence for the same semantic cue.
    events_by_cue: dict[str, list[Mapping[str, object]]] = {}
    for row in events.values():
        if (row.get("match") or {}).get("reason") == "accepted":
            events_by_cue.setdefault(_source_cue_id(row.get("cue_id")), []).append(row)
    groups: dict[str, list[tuple[float, list[str]]]] = {}
    for group in style_data.get("caption_groups", []):
        if not isinstance(group, Mapping) or group.get("observation_provenance") == ["transcript_only"]:
            continue
        try:
            moment = float(group["timestamp"])
        except (ValueError, TypeError, KeyError):
            continue
        for identity in group.get("tracklet_ids") or []:
            groups.setdefault(str(identity), []).append((moment, words(group.get("text"))))

    output = list(cues)
    promoted: list[str] = []
    for cue in list(cues):
        if (cue.get("timing_authority") != "visual_primary"
                or cue.get("semantic_reference_ids") or not cue.get("style_evidence_id")
                or cue.get("accepted_motion_authority")):
            continue
        identity = str(cue.get("visual_event_identity") or "")
        event = events.get(identity)
        phrase = words(cue.get("text"))
        if (not isinstance(event, Mapping) or (event.get("match") or {}).get("reason") != "accepted"
                or not 2 <= len(phrase) <= 6
                or (event.get("animation") or {}).get("detected")):
            continue
        observations = sorted(float(row["timestamp"]) for row in event.get("observations") or []
                              if isinstance(row, Mapping) and isinstance(row.get("timestamp"), (int, float))
                              and row.get("tracklet_id") == identity and words(row.get("text")) == phrase
                              and (row.get("composition") or {}).get("tracklet_ids") == [identity])
        if len(observations) < 3 or observations[-1] - observations[0] < 0.15:
            continue
        state_start = max(int(cue["start_frame"]), round(observations[0] * fps))
        state_end = min(int(cue["end_frame"]), round(min(float(event["end"]), observations[-1] + 0.1) * fps))
        if state_end - state_start < 2:
            continue
        matches = []
        for start in range(len(transcript) - len(phrase) + 1):
            if transcript_words[start:start + len(phrase)] != [[word] for word in phrase]:
                continue
            rows = transcript[start:start + len(phrase)]
            if (not 0 <= state_start - int(rows[0]["timeline_start_frame"]) <= round(2 * fps)
                    or int(rows[-1]["timeline_start_frame"]) >= state_end):
                continue
            ids = transcript_ids[start:start + len(phrase)]
            owners = [next((other for other in output if other is not cue
                            and value in (other.get("semantic_reference_ids") or other.get("source_cue_ids") or [])
                            and words(other.get("text")) == [word]), None)
                      for value, word in zip(ids, phrase)]
            if all(owners):
                matches.append((abs(state_start - int(rows[0]["timeline_start_frame"])), ids, owners))
        if not matches:
            continue
        _, ids, owners = min(matches, key=lambda row: row[0])
        cue.update(text=canonical.norm_text(event.get("observed_text")), start_frame=state_start,
                   end_frame=state_end, start=state_start / fps, end=state_end / fps,
                   duration_frames=state_end - state_start, duration=(state_end - state_start) / fps,
                   semantic_reference_ids=list(ids), source_cue_ids=list(ids),
                   raw={"timeline_start_frame": state_start, "timeline_end_frame": state_end},
                   animation_application_skip_reason="source_phrase_state_changed",
                   source_observed_phrase_state=True)
        for owner in owners:
            if (owner.get("timing_authority") == "transcript_fallback"
                    and len(owner.get("source_cue_ids") or []) == 1
                    and not owner.get("visual_event_identity") and not owner.get("style_evidence_id")
                    and int(owner["start_frame"]) < state_start
                    and 0 <= state_start - int(owner["end_frame"]) <= 1
                    and not any(
                        other is not event and (other.get("match") or {}).get("reason") == "accepted"
                        and any(isinstance(sample, Mapping)
                                and sample.get("tracklet_id") == other.get("visual_event_identity")
                                and isinstance(sample.get("timestamp"), (int, float))
                                and float(owner["start"]) <= sample["timestamp"] < state_start / fps
                                and words(sample.get("text")) == words(owner.get("text"))
                                for sample in other.get("observations") or [])
                        for other in events.values())):
                output.remove(owner)
                continue
            if int(owner["start_frame"]) >= state_end or int(owner["end_frame"]) <= state_start:
                continue
            if (owner.get("timing_authority") == "transcript_fallback"
                    or (owner.get("timing_authority") == "visual_primary"
                        and int(owner["start_frame"]) < state_start
                        and int(owner["end_frame"]) <= state_start + 2
                        and not owner.get("accepted_motion_authority"))):
                if int(owner["start_frame"]) >= state_start or state_start - int(owner["start_frame"]) < 2:
                    output.remove(owner)
                else:
                    owner["end_frame"] = state_start
                    owner["end"] = state_start / fps
                    owner["duration_frames"] = state_start - int(owner["start_frame"])
                    owner["duration"] = owner["duration_frames"] / fps
                    owner["raw"] = {**(owner.get("raw") or {}), "timeline_end_frame": state_start}
        promoted.append(str(cue["id"]))
    for cue in list(cues):
        if (cue.get("timing_authority") != "visual_primary"
                or cue.get("accepted_motion_authority")
                or not cue.get("style_evidence_id")
                or len(cue.get("semantic_reference_ids") or []) != 1):
            continue
        identity = str(cue.get("visual_event_identity") or "")
        event = events.get(identity)
        if (not isinstance(event, Mapping)
                or (event.get("match") or {}).get("reason") != "accepted"):
            continue
        # A confirmed scale-pop is a distinct animated object, not a safe
        # static phrase state to replace with another text geometry.
        motion = event.get("animation") if isinstance(event.get("animation"), Mapping) else {}
        if motion.get("detected") and motion.get("type") == "scale_pop":
            continue
        cue_text = words(cue.get("text"))
        if len(cue_text) != 1:
            continue
        own_id = str(cue["semantic_reference_ids"][0])
        if own_id not in positions:
            continue
        # A single source word can visibly persist across two adjacent spoken words.
        if positions[own_id] > 0:
            previous_id = transcript_ids[positions[own_id] - 1]
            previous = next((other for other in output if other is not cue
                             and previous_id in (other.get("semantic_reference_ids") or [])
                             and len(other.get("semantic_reference_ids") or []) == 1), None)
            if previous and previous.get("timing_authority") == "visual_primary":
                joined = (canonical.normalize_semantic_caption_text(previous["text"])
                          + canonical.normalize_semantic_caption_text(cue["text"]))
                previous_event = events.get(str(previous.get("visual_event_identity") or ""))
                for candidate in sorted(set(event.get("observed_texts") or [])):
                    if canonical.normalize_semantic_caption_text(candidate) != joined:
                        continue
                    positives = sorted(float(row["timestamp"]) for row in event.get("observations") or []
                                       if isinstance(row, Mapping) and row.get("text") == candidate
                                       and row.get("tracklet_id") == identity
                                       and isinstance(row.get("timestamp"), (int, float)))
                    if len(positives) < 3 or positives[-1] - positives[0] < 0.15:
                        continue
                    state_start = max(int(cue["start_frame"]), round(positives[0] * fps))
                    state_end = min(int(cue["end_frame"]), round(float(event["end"]) * fps))
                    if (state_end - state_start < 2
                            or not previous_event
                            or not any(isinstance(row, Mapping)
                                       and canonical.normalize_semantic_caption_text(row.get("text")) == joined
                                       and isinstance(row.get("timestamp"), (int, float))
                                       and 0 <= state_start / fps - float(row["timestamp"]) <= 3 / fps
                                       for row in previous_event.get("observations") or [])
                            or not int(previous["start_frame"]) < state_start
                            or int(previous["end_frame"]) > state_start + 1
                            or any(other is not previous and other is not cue
                                   and previous_id in (other.get("semantic_reference_ids") or [])
                                   and int(other["start_frame"]) < state_end
                                   and int(other["end_frame"]) > state_start
                                   for other in output)):
                        continue
                    if int(previous["end_frame"]) > state_start:
                        previous["end_frame"] = state_start
                        previous["end"] = state_start / fps
                        previous["duration_frames"] = state_start - int(previous["start_frame"])
                        previous["duration"] = previous["duration_frames"] / fps
                        previous["raw"] = {**(previous.get("raw") or {}), "timeline_end_frame": state_start}
                    cue.update(text=candidate, start_frame=state_start, end_frame=state_end,
                               start=state_start / fps, end=state_end / fps,
                               duration_frames=state_end - state_start,
                               duration=(state_end - state_start) / fps,
                               semantic_reference_ids=[previous_id, own_id],
                               source_cue_ids=[previous_id, own_id],
                               raw={"timeline_start_frame": state_start, "timeline_end_frame": state_end},
                               animation_application_skip_reason="source_phrase_state_changed",
                               source_observed_phrase_state=True)
                    promoted.append(str(cue["id"]))
                    break
                if str(cue["id"]) in promoted:
                    continue
        choice = None
        # Prefer this tracklet; a discarded OCR alias is eligible only when
        # its own frames prove the longer source state for the same word.
        candidates = [event] + [
            other for other in events_by_cue.get(own_id, [])
            if other is not event
            and float(other.get("start") or -1) < float(cue["end"])
            and float(other.get("end") or -1) > float(cue["start"])
            and not ((other.get("animation") or {}).get("detected")
                     and (other.get("animation") or {}).get("type") == "scale_pop")
        ]
        for source_event in candidates:
            source_identity = str(source_event.get("visual_event_identity") or "")
            for candidate in sorted(
                {str(value) for value in source_event.get("observed_texts") or []},
                key=lambda value: (-len(words(value)), value),
            ):
                phrase = words(candidate)
                if not (2 <= len(phrase) <= 6 and cue_text[0] in phrase):
                    continue
                owner_index = phrase.index(cue_text[0])
                start_index = positions[own_id] - owner_index
                if start_index < 0 or start_index + len(phrase) > len(transcript):
                    continue
                selected = transcript[start_index:start_index + len(phrase)]
                ids = transcript_ids[start_index:start_index + len(phrase)]
                if any(len(entry) != 1 or entry[0] != expected
                       for entry, expected in zip(transcript_words[start_index:start_index + len(phrase)], phrase)):
                    continue
                # No source-backed word in the phrase can already occupy the
                # proposed state; those words may be independently styled.
                observations = sorted(moment for moment, observed in groups.get(source_identity, [])
                                      if observed[:len(phrase)] == phrase)
                if len(observations) < 3 or observations[-1] - observations[0] < 0.15:
                    continue
                state_start = max(int(cue["start_frame"]), round(observations[0] * fps))
                state_end = int(cue["end_frame"])
                if state_end - state_start < 2:
                    continue
                if any(other is not cue
                       and other.get("timing_authority") == "visual_primary"
                       and any(value in (other.get("semantic_reference_ids") or []) for value in ids)
                       and int(other["start_frame"]) < state_end
                       and int(other["end_frame"]) > state_start
                       for other in output):
                    continue
                fallback = [other for other in output if other is not cue
                            and other.get("timing_authority") == "transcript_fallback"
                            and any(value in (other.get("source_cue_ids") or []) for value in ids)]
                if any(len(other.get("source_cue_ids") or []) != 1 for other in fallback):
                    continue
                choice = (candidate, ids, state_start, fallback, source_event)
                break
            if choice is not None:
                break
        if choice is None:
            continue
        candidate, ids, state_start, fallback, source_event = choice
        old_start = int(cue["start_frame"])
        if state_start - old_start >= max(5, round(0.20 * fps)):
            initial = dict(cue)
            initial["id"] = str(cue["id"]) + "_source_lead"
            initial["end_frame"] = state_start
            initial["end"] = state_start / fps
            initial["duration_frames"] = state_start - old_start
            initial["duration"] = (state_start - old_start) / fps
            initial["raw"] = {**(cue.get("raw") or {}), "timeline_end_frame": state_start}
            initial["animation_application_skip_reason"] = "source_phrase_state_changed"
            output.append(initial)
        cue["animation_application_skip_reason"] = "source_phrase_state_changed"
        if source_event is not event:
            # Bind both style and geometry to the observed phrase tracklet;
            # the original word tracklet is not evidence for its full bbox.
            cue["visual_event_identity"] = str(source_event["visual_event_identity"])
            cue["style_evidence_id"] = str(source_event["event_id"])
        cue["text"] = candidate
        cue["start_frame"] = state_start
        cue["start"] = state_start / fps
        cue["duration_frames"] = int(cue["end_frame"]) - state_start
        cue["duration"] = cue["duration_frames"] / fps
        cue["semantic_reference_ids"] = list(ids)
        cue["source_cue_ids"] = list(ids)
        cue["raw"] = {**(cue.get("raw") or {}), "timeline_start_frame": state_start}
        for word_cue in fallback:
            output.remove(word_cue)
        promoted.append(str(cue["id"]))
    output.sort(key=lambda cue: (int(cue["start_frame"]), int(cue["end_frame"]), str(cue["id"])))
    return output, promoted

def _apply_observed_phrase_geometry(
    cues: Sequence[dict[str, object]],
    styles: Mapping[int, dict[str, object]],
    style_data: Mapping[str, object],
    promoted_ids: Sequence[str],
) -> int:
    """Place confirmed phrase states using their own OCR boxes, not word boxes.

    Do not infer geometry from combined composition boxes or from transcript
    timing. Other visual titles and unverified phrase states are unchanged.
    """
    from statistics import median

    identities = {str(value) for value in promoted_ids}
    if not identities:
        return 0
    info = style_data.get("video_info") or {}
    width, height = info.get("width"), info.get("height")
    if not (isinstance(width, (int, float)) and width > 0
            and isinstance(height, (int, float)) and height > 0):
        return 0

    event_by_identity = {
        str(event.get("visual_event_identity")): event
        for event in style_data.get("caption_style_events", [])
        if isinstance(event, Mapping) and event.get("visual_event_identity")
    }
    changed = 0
    for cue in cues:
        if str(cue.get("id")) not in identities:
            continue
        identity = str(cue.get("visual_event_identity") or "")
        event = event_by_identity.get(identity)
        style = styles.get(int(cue["index"]))
        if not isinstance(event, Mapping) or not isinstance(style, dict):
            continue
        phrase = canonical.normalize_semantic_caption_text(cue.get("text"))
        boxes: list[list[float]] = []
        times: list[float] = []
        for observation in event.get("observations") or []:
            if not isinstance(observation, Mapping):
                continue
            if canonical.normalize_semantic_caption_text(observation.get("text")) != phrase:
                continue
            if str(observation.get("tracklet_id") or "") != identity:
                continue
            composition = observation.get("composition") or {}
            if (isinstance(composition, Mapping)
                    and composition.get("tracklet_ids") != [identity]):
                continue  # A merged OCR group is not this phrase's own bbox.
            bbox = observation.get("bbox")
            moment = observation.get("timestamp")
            if (not isinstance(bbox, list) or len(bbox) != 4
                    or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in bbox)
                    or not isinstance(moment, (int, float))):
                continue
            x1, y1, x2, y2 = map(float, bbox)
            if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                continue
            if not (float(cue["start"]) - 0.20 <= moment <= float(cue["end"]) + 0.20):
                continue
            boxes.append([x1, y1, x2, y2])
            times.append(float(moment))
        if len(boxes) < 3 or max(times) - min(times) < 0.15:
            continue

        x1, y1, x2, y2 = [median(row[i] for row in boxes) for i in range(4)]
        if x2 <= x1 or y2 <= y1:
            continue
        # Basic Title paragraph alignment does not change the position
        # anchor of its FCPXML adjust-transform. OCR provides a glyph bbox;
        # place the title object at its center regardless of text alignment.
        x = (x1 + x2) / 2
        y = (y1 + y2) / 2
        anchor = {"x": round(x / width, 5), "y": round(y / height, 5)}
        bounded_size = min(int(style["font_size_px"]), max(1, round((y2 - y1) * 1.15)))
        current_anchor = style.get("anchor") or {}
        # Reuse already-good placement: avoid visual drift on accepted phrase
        # states just because OCR median differs by a few pixels.
        if (abs(float(current_anchor.get("x", 0.5)) - anchor["x"]) < 0.025
                and abs(float(current_anchor.get("y", 0.5)) - anchor["y"]) < 0.01
                and bounded_size >= int(style["font_size_px"])):
            continue
        placement = dict(style.get("placement") or {})
        placement["normalized_bbox"] = [round(x1 / width, 5), round(y1 / height, 5),
                                        round(x2 / width, 5), round(y2 / height, 5)]
        placement["anchor"] = {**anchor, "coordinate_space": "normalized_frame"}
        style["placement"] = placement
        style["anchor"] = anchor
        # Bounding-box height is direct source evidence; never enlarge the
        # inherited word font to fill it. No global size adjustment.
        size = bounded_size
        if size < int(style["font_size_px"]):
            style["font_size_px"] = size
            style.pop("textplus_size", None)
            _ensure_textplus_size(style, width)
        cue["position_mode"] = "detected_fcpx"
        changed += 1
    return changed



def _center_adjacent_observed_phrase_titles(
    cues: Sequence[Mapping[str, object]],
    styles: Mapping[int, dict[str, object]],
    promoted_ids: Sequence[str],
) -> int:
    """Keep source-neighboring phrase glyphs centered on their OCR bbox.

    The OCR horizontal_align classifies the bbox's location in the frame.
    It does NOT describe the text paragraph alignment expected by Basic Title.
    In a simultaneous multi-title composition, treating it as left/right
    paragraph alignment moves glyphs off their observed bbox into neighbors.
    Preserve OCR geometry and typography; correct only this output adapter.
    """
    promoted = set(promoted_ids)
    adjusted = 0
    for cue in cues:
        if cue.get("id") not in promoted or cue.get("timing_authority") != "visual_primary":
            continue
        style = styles.get(int(cue["index"]))
        if not isinstance(style, dict) or style.get("alignment") not in {"left", "right"}:
            continue
        bbox = (style.get("placement") or {}).get("normalized_bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        if not all(isinstance(x, (int, float)) for x in bbox):
            continue
        if not (0 <= bbox[0] < bbox[2] <= 1 and 0 <= bbox[1] < bbox[3] <= 1):
            continue
        if bbox[2] - bbox[0] < .12:
            continue
        midpoint = (bbox[1] + bbox[3]) / 2
        for other in cues:
            if other is cue or other.get("timing_authority") != "visual_primary":
                continue
            if (other.get("visual_event_identity") == cue.get("visual_event_identity")
                    or int(other["start_frame"]) >= int(cue["end_frame"])
                    or int(other["end_frame"]) <= int(cue["start_frame"])):
                continue
            neighbor_style = styles.get(int(other["index"]))
            other_bbox = ((neighbor_style or {}).get("placement") or {}).get("normalized_bbox")
            if not isinstance(other_bbox, (list, tuple)) or len(other_bbox) != 4:
                continue
            if not all(isinstance(x, (int, float)) for x in other_bbox):
                continue
            neighbor_midpoint = (other_bbox[1] + other_bbox[3]) / 2
            vertical_gap = max(0, other_bbox[1] - bbox[3], bbox[1] - other_bbox[3])
            if abs(midpoint - neighbor_midpoint) > .025 and vertical_gap <= .02:
                # Do not rewrite source detection's horizontal_align field.
                # Only Resolve's paragraph layout is corrected.
                style["alignment"] = "center"
                adjusted += 1
                break
    return adjusted


def _suppress_unanchored_phrase_echoes(
    cues: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[str], dict[str, dict[str, object]]]:
    """Suppress only unsupported sentence echoes already represented by timed words.

    An unanchored OCR phrase is not an extra title when its constituent words
    already have independent semantic caption authority. Preserve all tokens
    (including legitimate co-visible words) in source analysis; omit only the
    duplicate from the executable caption projection.
    """
    import re

    def words(value: object) -> list[str]:
        return re.findall(r"\w+(?:['’]\w+)*", str(value or "").casefold())

    anchored = sorted(
        (
            cue for cue in cues
            if cue.get("semantic_reference_ids") or cue.get("source_cue_ids")
        ),
        key=lambda cue: (int(cue["start_frame"]), int(cue["end_frame"])),
    )
    omitted: list[str] = []
    style_donors: dict[str, dict[str, object]] = {}
    for cue in cues:
        if cue.get("semantic_reference_ids") or cue.get("source_cue_ids"):
            continue
        phrase = words(cue.get("text"))
        if len(phrase) < 3:
            continue
        begin, end = int(cue["start_frame"]), int(cue["end_frame"])
        matched, cursor = 0, 0
        word_matches: list[dict[str, object]] = []
        for word_cue in anchored:
            if int(word_cue["start_frame"]) >= end + 1:
                break
            if int(word_cue["end_frame"]) < begin:
                continue
            candidate = words(word_cue.get("text"))
            if len(candidate) != 1:
                continue
            try:
                cursor = phrase.index(candidate[0], cursor) + 1
            except ValueError:
                continue
            matched += 1
            word_matches.append(word_cue)
        # A phrase is redundant only when >=80% of its words are already
        # independently executable in source order (at least three matches).
        if matched >= 3 and 5 * matched >= 4 * len(phrase):
            phrase_id = str(cue["id"])
            omitted.append(phrase_id)
            # The deleted phrase may carry real OCR style evidence. Retain it
            # solely as a source of typography for unsupported transcript words;
            # never keep its executable title or change word timings.
            if cue.get("style_evidence_id") and cue.get("visual_event_identity"):
                style_donors[phrase_id] = cue
                for word_cue in word_matches:
                    if (word_cue.get("timing_authority") == "transcript_fallback"
                            and not word_cue.get("style_evidence_id")):
                        word_cue.setdefault("_suppressed_phrase_style_donor", phrase_id)
    removed = set(omitted)
    return [cue for cue in cues if str(cue["id"]) not in removed], omitted, style_donors



def _trim_exclusive_phrase_handoffs(
    cues: list[dict[str, object]], style_data: Mapping[str, object], fps: float,
) -> int:
    """Remove frame-quantization overlap between successive OCR phrase states.

    Require distinct, accepted, overlapping source boxes and *no* source frame
    observing both tracklets together. Genuine simultaneous source captions
    remain unchanged; only an earlier phrase's last frame can be trimmed.
    """
    events = {
        str(row.get("visual_event_identity")): row
        for row in style_data.get("caption_style_events", [])
        if isinstance(row, Mapping) and row.get("visual_event_identity")
        and (row.get("match") or {}).get("reason") == "accepted"
    }
    simultaneous = {
        frozenset(str(i) for i in group.get("tracklet_ids") or [])
        for group in style_data.get("caption_groups", [])
        if isinstance(group, Mapping) and len(group.get("tracklet_ids") or []) > 1
    }
    changed = 0
    for left in cues:
        if (left.get("timing_authority") != "visual_primary"
                or len(str(left.get("text") or "").split()) < 2):
            continue
        left_id = str(left.get("visual_event_identity") or "")
        first = events.get(left_id)
        if not first:
            continue
        box_a = (first.get("placement") or {}).get("normalized_bbox")
        if not isinstance(box_a, list) or len(box_a) != 4:
            continue
        for right in cues:
            if (right is left or right.get("timing_authority") != "visual_primary"
                    or len(str(right.get("text") or "").split()) < 2
                    or not (int(left["start_frame"]) < int(right["start_frame"])
                            < int(left["end_frame"]) <= int(right["start_frame"]) + 1)):
                continue
            right_id = str(right.get("visual_event_identity") or "")
            second = events.get(right_id)
            if (not second or right_id == left_id
                    or any({left_id, right_id}.issubset(group) for group in simultaneous)):
                continue
            box_b = (second.get("placement") or {}).get("normalized_bbox")
            if not isinstance(box_b, list) or len(box_b) != 4:
                continue
            overlap = max(0., min(box_a[2], box_b[2]) - max(box_a[0], box_b[0])) * max(
                0., min(box_a[3], box_b[3]) - max(box_a[1], box_b[1]))
            area_b = max(0., box_b[2] - box_b[0]) * max(0., box_b[3] - box_b[1])
            if not area_b or overlap / area_b < 0.75:
                continue
            left["end_frame"] = int(right["start_frame"])
            left["end"] = left["end_frame"] / fps
            left["duration_frames"] = left["end_frame"] - int(left["start_frame"])
            left["duration"] = left["duration_frames"] / fps
            left["raw"] = {**(left.get("raw") or {}), "timeline_end_frame": left["end_frame"]}
            changed += 1
            break
    return changed


def _group_rapid_transcript_fallbacks(
    cues: list[dict[str, object]], fps: float,
) -> tuple[list[dict[str, object]], int]:
    """Render short, unobserved consecutive speech as a readable static phrase.

    Source-visible captions keep their exact observed windows. Do not invent
    persistence or join across a transcript segment/visual composition.
    """
    min_frames = max(1, round(0.35 * fps))
    target_frames = max(min_frames, round(0.45 * fps))
    max_frames = max(target_frames, round(0.95 * fps))
    visual = [cue for cue in cues if cue.get("timing_authority") == "visual_primary"]

    def transcript_word(cue: Mapping[str, object]) -> tuple[int, int] | None:
        raw = cue.get("raw")
        if (cue.get("timing_authority") != "transcript_fallback"
                or not isinstance(raw, Mapping)
                or not isinstance(raw.get("segment_index"), int)
                or not isinstance(raw.get("word_index"), int)
                or len(cue.get("source_cue_ids") or []) != 1):
            return None
        return int(raw["segment_index"]), int(raw["word_index"])

    def visually_clear(start: int, end: int) -> bool:
        return not any(
            int(cue["start_frame"]) < end and int(cue["end_frame"]) > start
            for cue in visual
        )

    def can_add(group: list[dict[str, object]], next_cue: dict[str, object]) -> bool:
        prior, initial = group[-1], group[0]
        previous_word, next_word = transcript_word(prior), transcript_word(next_cue)
        if (previous_word is None or next_word is None
                or next_word != (previous_word[0], previous_word[1] + 1)
                or int(next_cue["start_frame"]) - int(prior["end_frame"]) not in (0, 1)
                or len(group) >= 4
                or int(next_cue["end_frame"]) - int(initial["start_frame"]) > max_frames
                or len(" ".join(str(c["text"]) for c in [*group, next_cue])) > 28
                or str(prior["text"]).rstrip().endswith((".", "?", "!"))):
            return False
        start, end = int(initial["start_frame"]), int(next_cue["end_frame"])
        return visually_clear(start, end)

    output: list[dict[str, object]] = []
    grouped = 0
    index = 0
    while index < len(cues):
        cue = cues[index]
        duration = int(cue["end_frame"]) - int(cue["start_frame"])
        if transcript_word(cue) is None or duration >= min_frames:
            output.append(cue)
            index += 1
            continue
        group = [cue]
        for next_cue in cues[index + 1:index + 4]:
            if not can_add(group, next_cue):
                break
            group.append(next_cue)
            span = int(group[-1]["end_frame"]) - int(group[0]["start_frame"])
            if span >= target_frames:
                # Keep a short terminal word with its phrase when it fits,
                # instead of leaving another blink immediately afterwards.
                if (index + len(group) < len(cues)
                        and str(cues[index + len(group)]["text"]).rstrip().endswith((".", "?", "!"))
                        and int(cues[index + len(group)]["end_frame"]) - int(cues[index + len(group)]["start_frame"]) < min_frames
                        and can_add(group, cues[index + len(group)])):
                    group.append(cues[index + len(group)])
                break
        if (len(group) < 3 or int(group[-1]["end_frame"]) - int(cue["start_frame"]) < min_frames):
            output.append(cue)
            index += 1
            continue
        # Never change timings of observed visual titles; replace N fallback
        # words by one editable static title spanning their *existing* window.
        merged = dict(group[0])
        merged["text"] = " ".join(str(item["text"]) for item in group)
        merged["end_frame"] = int(group[-1]["end_frame"])
        merged["end"] = merged["end_frame"] / fps
        merged["duration_frames"] = merged["end_frame"] - int(merged["start_frame"])
        merged["duration"] = merged["duration_frames"] / fps
        merged["source_cue_ids"] = [sid for item in group for sid in item["source_cue_ids"]]
        merged["semantic_source_cue_ids"] = list(merged["source_cue_ids"])
        merged["transcript_text"] = merged["text"]
        merged["transcript_window"] = [int(merged["start_frame"]), merged["end_frame"]]
        raw = dict(group[0]["raw"])
        raw["timeline_end_frame"] = merged["end_frame"]
        merged["raw"] = raw
        merged["fallback_phrase_member_ids"] = [str(item["id"]) for item in group]
        donors = {str(item.get("_suppressed_phrase_style_donor") or "") for item in group}
        if len(donors) != 1:
            merged.pop("_suppressed_phrase_style_donor", None)
        output.append(merged)
        grouped += len(group) - 1
        index += len(group)
    return output, grouped


def _source_word_agreement(text: str, observed: str) -> float:
    """How strongly source OCR actually supports this semantic label (not its cue ID)."""
    import re

    target = re.sub(r"[^\w]", "", text.casefold())
    sample = re.sub(r"[^\w]", "", observed.casefold())
    if not target or not sample:
        return 0.0
    if target == sample:
        return 1.0
    if len(target) >= 4 and target in sample:
        return 1.0
    if len(sample) >= 4 and sample in target and len(sample) >= 0.75 * len(target):
        return len(sample) / len(target)
    return SequenceMatcher(None, target, sample).ratio()


def _reconcile_source_visual_instances(
    cues: list[dict[str, object]], style_data: Mapping[str, object], fps: float
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Keep OCR aliases from becoming simultaneous copies of one spoken caption.

    This is an execution projection: raw visual identities/observations remain intact
    in the source intelligence and no unrelated co-visible semantic IDs are merged.
    """
    events = {
        str(row.get("event_id") or ""): row
        for row in style_data.get("caption_style_events", [])
        if isinstance(row, Mapping) and row.get("event_id")
    }
    if not events:
        return cues, {"removed_alias_ids": [], "trimmed_windows": []}
    evidence: dict[str, tuple[int, float, list[tuple[float, float]]]] = {}
    for cue in cues:
        event = events.get(str(cue.get("style_evidence_id") or ""))
        if not event:
            continue
        observations = event.get("observations")
        if not isinstance(observations, list):
            continue
        samples = [
            (float(o["timestamp"]), _source_word_agreement(str(cue["text"]), str(o.get("text") or "")))
            for o in observations
            if isinstance(o, Mapping) and isinstance(o.get("timestamp"), (int, float))
        ]
        evidence[str(cue["id"])] = (
            sum(score >= 0.80 for _, score in samples),
            max((score for _, score in samples), default=0.0),
            samples,
        )

    # A semantic word may have many OCR aliases, but each source-backed word
    # should be emitted once at a given instant unless distinct same-word
    # instances are proved by their independent source observations.
    by_semantic: dict[tuple[tuple[str, ...], str], list[dict[str, object]]] = {}
    for cue in cues:
        ids = cue.get("semantic_reference_ids") or []
        if ids and cue.get("style_evidence_id") in events:
            by_semantic.setdefault((tuple(str(x) for x in ids), canonical.normalize_semantic_caption_text(cue["text"])), []).append(cue)

    def separately_observed(left: Mapping[str, object], right: Mapping[str, object], word: str) -> bool:
        """Two same-word titles are allowed only with separate same-frame OCR boxes."""
        def positives(event: Mapping[str, object]) -> dict[int, list[float]]:
            found = {}
            for observation in event.get("observations") or []:
                if not isinstance(observation, Mapping):
                    continue
                if _source_word_agreement(word, str(observation.get("text") or "")) < 0.80:
                    continue
                box = observation.get("bbox")
                frame = observation.get("frame_index")
                if (isinstance(frame, int) and isinstance(box, list) and len(box) == 4
                        and all(isinstance(v, (int, float)) for v in box)):
                    found[frame] = [float(v) for v in box]
            return found

        a, b = positives(left), positives(right)
        separate = 0
        for frame in a.keys() & b.keys():
            ax1, ay1, ax2, ay2 = a[frame]
            bx1, by1, bx2, by2 = b[frame]
            ix = max(0.0, min(ax2, bx2) - max(ax1, bx1))
            iy = max(0.0, min(ay2, by2) - max(ay1, by1))
            area = min(max(1.0, (ax2-ax1)*(ay2-ay1)), max(1.0, (bx2-bx1)*(by2-by1)))
            if ix * iy / area <= 0.05:
                separate += 1
        return separate >= 2

    omitted: set[str] = set()
    for candidates in by_semantic.values():
        candidates.sort(key=lambda c: (int(c["start_frame"]), int(c["end_frame"])))
        clusters: list[list[dict[str, object]]] = []
        boundary = -1
        for cue in candidates:
            if not clusters or int(cue["start_frame"]) > boundary + 1:
                clusters.append([])
                boundary = -1
            clusters[-1].append(cue)
            boundary = max(boundary, int(cue["end_frame"]))
        for cluster in clusters:
            if len(cluster) == 1:
                continue
            ids = [str(cue["id"]) for cue in cluster]
            if any(identifier not in evidence for identifier in ids):
                continue  # Older data without source OCR evidence must not be guessed away.
            # Several tracklets with no recognizable instance and wholly
            # unrelated OCR text must not masquerade as semantic caption words.
            if all(evidence[identifier][1] < 0.50 for identifier in ids):
                omitted.update(ids)
                continue
            winner = max(
                cluster,
                key=lambda cue: (
                    evidence[str(cue["id"])][0],
                    int(cue["end_frame"]) - int(cue["start_frame"]),
                    evidence[str(cue["id"])][1],
                    -int(cue["start_frame"]),
                ),
            )
            winner_id = str(winner["id"])
            for cue in cluster:
                if str(cue["id"]) == winner_id:
                    continue
                if separately_observed(
                    events[str(winner.get("style_evidence_id"))],
                    events[str(cue.get("style_evidence_id"))],
                    str(winner["text"]),
                ):
                    continue  # Two distinct same-word captions are proven in source frames.
                omitted.add(str(cue["id"]))
            # A full-word detection may be followed by adjacent complementary
            # OCR fragments of that same word. Their observed intervals support
            # continuity, but each fragment is not another full caption.
            if evidence[winner_id][0] > 0:
                fragments = [
                    cue for cue in cluster if str(cue["id"]) in omitted
                    and evidence[str(cue["id"])][1] >= 0.55
                ]
                if fragments and all(
                    int(cue["start_frame"]) <= int(winner["end_frame"]) + 1
                    or int(winner["start_frame"]) <= int(cue["end_frame"]) + 1
                    for cue in fragments
                ):
                    winner["end_frame"] = max([int(winner["end_frame"])] + [int(c["end_frame"]) for c in fragments])
                    winner["start_frame"] = min([int(winner["start_frame"])] + [int(c["start_frame"]) for c in fragments])
                    winner["start"] = winner["start_frame"] / fps
                    winner["end"] = winner["end_frame"] / fps
                    winner["duration_frames"] = winner["end_frame"] - winner["start_frame"]
                    winner["duration"] = winner["duration_frames"] / fps

    # A missed OCR read can reappear a few frames after a confirmed word,
    # under the same transcript ID but inside a DIFFERENT source text region.
    # Only discard it if source boxes demonstrate that it belongs to that
    # other caption. Strongly observed repeats and independent compositions
    # must survive even when they share a transcript cue ID.
    for candidates in by_semantic.values():
        anchors = [
            cue for cue in candidates
            if str(cue["id"]) not in omitted
            and evidence.get(str(cue["id"]), (0, 0.0, []))[0] >= 2
        ]
        for cue in candidates:
            cid = str(cue["id"])
            event = events.get(str(cue.get("style_evidence_id") or ""))
            observations = event.get("observations") if event else None
            if (cid in omitted or cid not in evidence or evidence[cid][0] != 0
                    or not isinstance(observations, list) or len(observations) != 1):
                continue
            sample = observations[0]
            if not isinstance(sample, Mapping):
                continue
            box, timestamp = sample.get("bbox"), sample.get("timestamp")
            if (not isinstance(timestamp, (int, float)) or not isinstance(box, list)
                    or len(box) != 4 or not all(isinstance(v, (int, float)) for v in box)):
                continue
            # Use the confirmed caption's own duration to bound a near miss;
            # never merge arbitrarily distant repeats of the same word.
            if not any(
                anchor is not cue
                and 0 <= int(cue["start_frame"]) - int(anchor["end_frame"])
                <= int(anchor["end_frame"]) - int(anchor["start_frame"])
                for anchor in anchors
            ):
                continue
            area = (box[2] - box[0]) * (box[3] - box[1])
            if area <= 0:
                continue
            semantic_ids = set(cue.get("semantic_reference_ids") or [])
            for other in events.values():
                if (other is event or _source_cue_id((other.get("semantic_reference") or {}).get("cue_id")) in semantic_ids
                        or not float(other.get("start") or 0) <= timestamp <= float(other.get("end") or 0)):
                    continue
                for observed in other.get("observations") or []:
                    if not isinstance(observed, Mapping):
                        continue
                    other_box, other_time = observed.get("bbox"), observed.get("timestamp")
                    if (not isinstance(other_time, (int, float))
                            or abs(other_time - timestamp) > 2 / fps
                            or not isinstance(other_box, list) or len(other_box) != 4
                            or not all(isinstance(v, (int, float)) for v in other_box)
                            or _source_word_agreement(str(other.get("text") or ""), str(observed.get("text") or "")) < 0.80):
                        continue
                    ix = max(0.0, min(box[2], other_box[2]) - max(box[0], other_box[0]))
                    iy = max(0.0, min(box[3], other_box[3]) - max(box[1], other_box[1]))
                    if ix * iy / area >= 0.80:
                        omitted.add(cid)
                        break
                if cid in omitted:
                    break

    kept = [cue for cue in cues if str(cue["id"]) not in omitted]
    trimmed: list[dict[str, object]] = []
    for cue in kept:
        cid = str(cue["id"])
        if cid not in evidence:
            continue
        samples = evidence[cid][2]
        positives = sorted(time for time, score in samples if score >= 0.80)
        # A single OCR match cannot establish the duration of a visual word.
        if len(positives) < 2:
            continue
        first, last = positives[0], positives[-1]
        early_other = sorted(time for time, score in samples if time < first and score < 0.45)
        later_other = sorted(time for time, score in samples if time > last and score < 0.45)
        old_start, old_end = int(cue["start_frame"]), int(cue["end_frame"])
        new_start, new_end = old_start, old_end
        # Do not guess a fade. These bounds only follow a tracklet that
        # subsequently (or previously) recognized a *different* source word.
        if len(early_other) >= 2 and early_other[-1] - early_other[0] >= 0.07:
            bound = int((early_other[-1] + first) / 2 * fps)
            if old_start < bound < old_end:
                new_start = bound
        if len(later_other) >= 2 and later_other[-1] - later_other[0] >= 0.07:
            bound = int(round((last + later_other[0]) / 2 * fps)) + 1
            if old_start < bound < old_end:
                new_end = bound
        if new_end <= new_start or (new_start, new_end) == (old_start, old_end):
            continue
        cue.update({
            "start_frame": new_start, "end_frame": new_end,
            "start": new_start / fps, "end": new_end / fps,
            "duration_frames": new_end - new_start,
            "duration": (new_end - new_start) / fps,
            # Keep source animation evidence in intelligence. The compiler must
            # not retarget old keyframes onto this corrected visibility window.
            "animation_application_skip_reason": "source_visibility_window_changed",
        })
        trimmed.append({
            "token_id": cid,
            "previous_start": old_start, "previous_end": old_end,
            "new_start": new_start, "new_end": new_end,
            "animation_disposition": "static_fallback",
        })
    for index, cue in enumerate(kept, 1):
        cue["index"] = index
    return kept, {"removed_alias_ids": sorted(omitted), "trimmed_windows": trimmed}


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
            cue.get("visual_event_identity")
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
        style = styles.get(int(cue["index"]))
        if style is None:
            continue
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
        # Visibility authority outranks animation: do not attach the original
        # keyframes to a source-corrected time window.
        if cue.get("animation_application_skip_reason"):
            continue
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
    phrase_style_donors: dict[str, dict[str, object]] = {}
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
            visual_cues, visual_info = render_visual_compositions(compositions, generic_ids, fps, style_data)
            visual_cues, source_reconciliation = _reconcile_source_visual_instances(visual_cues, style_data, fps)
            visual_info["source_reconciliation"] = source_reconciliation
            visual_info["render_token_count"] = len(visual_cues)
            visual_info["semantic_reference_occurrence_count"] = sum(
                len(cue.get("semantic_reference_ids") or []) for cue in visual_cues
            )
            visual_info["semantic_reference_distinct_count"] = len({
                semantic_id for cue in visual_cues
                for semantic_id in cue.get("semantic_reference_ids") or []
            })
            referenced = {
                semantic_id
                for cue in visual_cues
                for semantic_id in cue.get("semantic_reference_ids") or []
            }
            absent_ids: list[str] = []
            fallback_cues: list[dict[str, object]] = []
            for semantic_cue in semantic_cues:
                source_ids = [str(value) for value in semantic_cue.get("source_cue_ids") or []]
                timing_authority = str(semantic_cue.get("timing_authority") or "")
                absent_source_ids = [semantic_id for semantic_id in source_ids if semantic_id not in referenced]
                for semantic_id in source_ids:
                    if semantic_id in referenced:
                        continue
                    absent_ids.append(semantic_id)
                    if timing_authority != "transcript_fallback":
                        raise StandaloneTextplusError(
                            "semantic fallback disposition is unresolved: " + semantic_id
                        )
                if absent_source_ids:
                    if len(absent_source_ids) != len(source_ids):
                        raise StandaloneTextplusError("semantic cue is only partially represented visually")
                    fallback_cues.append(dict(semantic_cue))
            for cue in visual_cues:
                cue["source_cue_ids"] = []
            cues = sorted(
                [*visual_cues, *fallback_cues],
                key=lambda cue: (
                    int(cue.get("start_frame") or 0),
                    int(cue.get("end_frame") or 0),
                    str(cue.get("id") or ""),
                ),
            )
            # Direct source observations take priority over a transcript-only
            # word sequence when the whole phrase was visibly persistent.
            cues, visual_phrase_ids = _prefer_source_visible_phrases(cues, style_data, fps)
            visual_info["source_visual_phrase_promoted_ids"] = visual_phrase_ids
            cues, expanded_states = _project_observed_phrase_states(cues, style_data, generic, fps)
            visual_info["source_observed_phrase_state_ids"] = expanded_states
            # Otherwise suppress unanchored OCR segment echoes.
            cues, phrase_echo_ids, phrase_style_donors = _suppress_unanchored_phrase_echoes(cues)
            visual_info["omitted_segment_echo_ids"].extend(phrase_echo_ids)
            cues, grouped_fallback_words = _group_rapid_transcript_fallbacks(cues, fps)
            visual_info["grouped_rapid_fallback_word_count"] = grouped_fallback_words
            visual_info["exclusive_phrase_handoffs_trimmed"] = _trim_exclusive_phrase_handoffs(
                cues, style_data, fps
            )
            visual_info["render_token_count"] = sum(
                cue.get("timing_authority") == "visual_primary" for cue in cues
            )
            visual_info["semantic_reference_occurrence_count"] = sum(
                len(cue.get("semantic_reference_ids") or []) for cue in cues
                if cue.get("timing_authority") == "visual_primary"
            )
            visual_info["semantic_reference_distinct_count"] = len({
                semantic_id for cue in cues if cue.get("timing_authority") == "visual_primary"
                for semantic_id in cue.get("semantic_reference_ids") or []
            })
            referenced = {
                semantic_id for cue in cues if cue.get("timing_authority") == "visual_primary"
                for semantic_id in cue.get("semantic_reference_ids") or []
            }
            absent_ids = [
                str(semantic_id) for cue in cues if cue.get("timing_authority") == "transcript_fallback"
                for semantic_id in cue.get("source_cue_ids") or []
            ]
            # Visual and transcript fallback cues originally carry *different*
            # index namespaces; they must be unique before style/placement lookup.
            for index, cue in enumerate(cues, 1):
                cue["index"] = index
            semantic_execution_ids = [
                semantic_id for semantic_id in generic_ids if semantic_id in referenced or semantic_id in absent_ids
            ]
            if semantic_execution_ids != generic_ids:
                raise StandaloneTextplusError("semantic ledger order/cardinality changed")
            visual_info["semantic_coverage_exact"] = True
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
    # Grouped transcript-only phrases have no source-backed bounding box.
    # The source profile describes *individual* words, so avoid reusing its
    # enormous single-word font size for a multiword fallback composition.
    video_info = style_data.get("video_info") if isinstance(style_data.get("video_info"), Mapping) else {}
    frame_width = video_info.get("width")
    if isinstance(frame_width, (int, float)) and frame_width > 0:
        for cue in cues:
            if not cue.get("fallback_phrase_member_ids"):
                continue
            idx = int(cue["index"])
            contract = dict(cue_styles.get(idx, style))
            text_chars = len(str(cue["text"]))
            safe_px = min(round(frame_width * 0.09), round(0.82 * frame_width / (0.58 * max(1, text_chars))))
            contract["font_size_px"] = min(int(contract["font_size_px"]), max(1, safe_px))
            contract.pop("textplus_size", None)
            contract["style_authority"] = "safe_transcript_fallback_phrase"
            cue_styles[idx] = contract
            cue["position_mode"] = "fallback_center"
    # When a redundant source OCR phrase is suppressed, its *accepted* style
    # can still inform transcript words it represented. This is generic for
    # any Reel: no text, timestamps, identities or source video are altered.
    if phrase_style_donors:
        donor_styles: dict[str, dict[str, object]] = {}
        for donor_id, donor_cue in phrase_style_donors.items():
            # A donor is unanchored: resolve by its unique visual-event identity.
            probe = {**donor_cue, "index": 1}
            try:
                recovered, _ = resolve_visual_style_authority([probe], effective_style_data, fps)
            except StandaloneTextplusError:
                continue  # Unverified OCR style is not grounds for guessing.
            if 1 in recovered:
                donor_styles[donor_id] = recovered[1]
        for cue in cues:
            donor_id = str(cue.pop("_suppressed_phrase_style_donor", ""))
            idx = int(cue.get("index") or 0)
            if (donor_id in donor_styles and idx not in direct_styles
                    and cue.get("timing_authority") == "transcript_fallback"
                    and not cue.get("fallback_phrase_member_ids")):
                contract = dict(donor_styles[donor_id])
                contract["style_authority"] = "accepted_source_phrase_fallback"
                cue_styles[idx] = contract
                cue["position_mode"] = "detected_fcpx"
    metrics["accepted_source_phrase_fallback_style_count"] = sum(
        style.get("style_authority") == "accepted_source_phrase_fallback"
        for style in cue_styles.values()
    )
    video_info = style_data.get("video_info") if isinstance(style_data.get("video_info"), Mapping) else {}
    phrase_geometry_count = _apply_observed_phrase_geometry(
        cues, cue_styles, effective_style_data,
        (lifecycle_info.get("visual_compositions") or {}).get("source_observed_phrase_state_ids") or [],
    )
    metrics["source_observed_phrase_geometry_count"] = phrase_geometry_count
    static_style_count = apply_static_style_authority(cues, cue_styles, video_info.get("width"))
    metrics["adjacent_observed_phrase_alignment_count"] = _center_adjacent_observed_phrase_titles(
        cues, cue_styles,
        (lifecycle_info.get("visual_compositions") or {}).get("source_observed_phrase_state_ids") or [],
    )
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
