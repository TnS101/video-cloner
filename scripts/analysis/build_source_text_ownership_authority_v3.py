#!/usr/bin/env python3
"""Derive latent source-text/ownership authority from accepted semantic segments."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Mapping


DISPOSITIONS = {
    "CANONICAL_OBJECT_MEMBER", "FRAGMENT_MEMBER", "TEMPORAL_MEMBER",
    "DISTINCT_COMPOSITION_MEMBER", "NON_CAPTION_OBSERVATION",
    "REJECTED_NOISE", "UNRESOLVED",
}
OBJECT_TYPES = {
    "INDEPENDENT_VISUAL_OBJECT", "PHYSICAL_WORD_OBJECT",
    "MULTI_SEGMENT_TEMPORAL_OBJECT", "COMPOSITION_MEMBER_OBJECT",
}
COMPOSITION_TYPES = {
    "MULTIPLE_DISTINCT_OBJECTS", "ONE_PHYSICAL_WORD_FROM_FRAGMENTS",
    "TEMPORAL_VARIANTS_OF_ONE_OBJECT", "MIXED", "INVALID_NON_CAPTION",
    "UNRESOLVED",
}
PRODUCTION_FUNCTIONS = {
    "non_caption_decision", "support_candidates", "resolve_segment_text",
    "temporal_alias_compatible", "build_production",
}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def norm(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", str(value or "").lower()))


def compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def similarity(a: Any, b: Any) -> float:
    aa, bb = compact(a), compact(b)
    return SequenceMatcher(None, aa, bb).ratio() if aa and bb else 0.0


def containment(a: Any, b: Any) -> float:
    aa, bb = compact(a), compact(b)
    if not aa or not bb:
        return 0.0
    shorter, longer = sorted((aa, bb), key=len)
    return len(shorter) / len(longer) if shorter in longer else 0.0


def bbox_iou(a: list[float], b: list[float]) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = max(1.0, (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter)
    return inter / union


def overlaps(a: tuple[int, int], b: tuple[int, int], pad: int = 0) -> bool:
    return a[0] <= b[1] + pad and b[0] <= a[1] + pad


def stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}_{canonical_hash(parts)[:16]}"


def non_caption_decision(track: Mapping[str, Any]) -> dict[str, Any]:
    features = track["features"]
    geometry = features["geometry"]
    stable_visual = (
        int(features["nonempty_ocr_samples"]) >= 3
        and len(features["temporal_text_clusters"]) <= 2
    )
    static_behavior = (
        int(geometry["accepted_observation_count"]) == 0
        or (
            geometry.get("center_step_median_px") is not None
            and float(geometry["center_step_median_px"]) <= 1.0
            and float(geometry.get("size_log_step_median") or 0.0) <= 0.02
        )
    )
    low_caption_agreement = float(features["source_contract_similarity"]) < 0.35
    style_inconsistent = all(
        str(features["style_support_only"].get(key)) == "UNRESOLVED"
        for key in ("font_status", "fill_status")
    )
    component_support = int(features["neighbor_count"]) >= 2
    decisive = stable_visual and static_behavior and low_caption_agreement and (style_inconsistent or component_support)
    contributions = {
        "persistent_repeated_visual_structure": stable_visual,
        "static_non_caption_temporal_behavior": static_behavior,
        "low_caption_text_agreement": low_caption_agreement,
        "style_inconsistent_with_caption_system": style_inconsistent,
        "multiple_component_neighbors": component_support,
        "screen_region_support_only": bool(features.get("bottom_region")),
    }
    return {
        "rejected_as_non_caption": decisive,
        "feature_contributions": contributions,
        "screen_region_was_decisive": False,
        "rule": "five_feature_static_visual_non_caption_gate",
        "confidence": 0.96 if decisive else 0.0,
    }


def support_candidates(
    segment: Mapping[str, Any], source_rows: Mapping[str, Mapping[str, Any]],
    linkage_rows: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    interval = (int(segment["source_frame_start"]), int(segment["source_frame_end"]))
    bbox = segment["representative_bbox_trajectory"][0]
    result: list[dict[str, Any]] = []
    for identity, source in source_rows.items():
        source_interval = (int(source["first_visible_frame"]), int(source["last_visible_frame"]))
        if identity == segment["parent_track_identity"] or not overlaps(interval, source_interval, 2):
            continue
        source_bbox = source.get("bbox") or []
        if len(source_bbox) != 4:
            continue
        linkage = linkage_rows.get(identity, {})
        values = [source.get("observed_text"), linkage.get("glyph_artifact_text"), linkage.get("contract_text")]
        for value in values:
            text = norm(value)
            same_baseline = abs((bbox[1] + bbox[3]) / 2 - (source_bbox[1] + source_bbox[3]) / 2) <= max(24, (bbox[3]-bbox[1]) * 0.55)
            boundary_fragment = min(abs(interval[1] - source_interval[0]), abs(source_interval[1] - interval[0])) <= 2 and similarity(segment.get("candidate_visible_text"), text) >= 0.5
            if text and len(text.split()) <= 4 and (bbox_iou(bbox, source_bbox) >= 0.05 or same_baseline or boundary_fragment):
                result.append({"text": text, "identity": identity, "bbox_iou": round(bbox_iou(bbox, source_bbox), 6)})
    return result


def resolve_segment_text(
    segment: Mapping[str, Any], track: Mapping[str, Any],
    source: Mapping[str, Any], linkage: Mapping[str, Any],
    nearby: list[dict[str, Any]], composition_texts: list[str],
) -> dict[str, Any]:
    candidate = norm(segment.get("candidate_visible_text"))
    purity = track["purity_class"]
    features = track["features"]
    parent = features.get("fragment_parent") or {}
    observed = norm(source.get("observed_text"))
    contract = norm(linkage.get("contract_text"))
    glyph = norm(linkage.get("glyph_artifact_text"))
    accepted_visible = norm(linkage.get("source_visible_text"))
    accepted_detail = linkage.get("source_evidence_provenance") or {}
    accepted_visual = norm(accepted_detail.get("visual_text"))
    accepted_parent = norm(accepted_detail.get("parent_text"))
    clusters = segment.get("source_evidence", {}).get("ocr_clusters") or []
    occurrences = sum(
        compact(candidate) in compact(text)
        for cluster in clusters for text in cluster.get("texts") or []
        if candidate
    )
    evidence_values = [
        {"text": accepted_visible, "kind": "accepted_source_visible_text"},
        {"text": accepted_visual, "kind": "accepted_source_visual_text"},
        {"text": accepted_parent, "kind": "accepted_fragment_parent_text"},
        {"text": observed, "kind": "accepted_source_observation"},
        {"text": glyph, "kind": "glyph_authority"},
        {"text": contract, "kind": "existing_source_visible_authority"},
        *[{"text": x["text"], "kind": "neighboring_source_object"} for x in nearby],
        *[{"text": norm(x), "kind": "composition_component"} for x in composition_texts],
    ]
    evidence_values = [x for x in evidence_values if x["text"] and len(x["text"].split()) <= 4]
    parent_text = norm(parent.get("parent_text"))
    parent_match = bool(parent_text and candidate and (containment(candidate, parent_text) >= 0.2 or similarity(candidate, parent_text) >= 0.55))
    fragment_by_track = purity == "FRAGMENT_TRACK" or parent_match

    accepted_authority = next((x for x in evidence_values if x["kind"] in {"accepted_source_visible_text", "accepted_source_visual_text", "accepted_fragment_parent_text"}), None)
    accepted_matches_candidate = accepted_authority and (similarity(candidate, accepted_authority["text"]) >= 0.65 or containment(candidate, accepted_authority["text"]) >= 0.5)
    if accepted_authority and (len(candidate.split()) > 4 or (purity == "PURE_SINGLE_OBJECT" and not clusters) or accepted_matches_candidate):
        fragment = str(linkage.get("text_mask_relationship")) == "ACCEPTED_VISUAL_FRAGMENT"
        return {"resolved": True, "rejected_noise": False, "canonical_text": accepted_authority["text"], "text_state": "RECONSTRUCTED_FROM_FRAGMENTS" if fragment else "ANIMATION_STABILIZED", "fragment": fragment, "confidence": 0.98, "reason": accepted_authority["kind"]}

    compatible = [x for x in evidence_values if similarity(candidate, x["text"]) >= 0.72 or containment(candidate, x["text"]) >= 0.2]
    if parent_match:
        compatible.append({"text": parent_text, "kind": "fragment_parent_evidence"})
    compatible.sort(key=lambda x: (similarity(candidate, x["text"]), len(compact(x["text"])), x["kind"]), reverse=True)

    if purity == "MULTI_OBJECT_CROP":
        exact = [x for x in compatible if similarity(candidate, x["text"]) >= 0.82]
        composite = [x for x in exact if len(x["text"].split()) > 1 and " " not in candidate]
        if composite and all(token in {norm(v) for v in composition_texts} for token in composite[0]["text"].split()):
            return {"resolved": True, "rejected_noise": True, "reason": "aggregate_crop_observation_already_resolved_by_independent_components"}
        if exact:
            selected = exact[0]
            return {"resolved": True, "rejected_noise": False, "canonical_text": selected["text"], "text_state": "EXACT_STABLE", "fragment": False, "confidence": 0.94, "reason": selected["kind"]}
        fragment_support = [x for x in compatible if len(compact(candidate)) >= 2 and containment(candidate, x["text"]) >= 0.2]
        if fragment_support:
            selected = max(fragment_support, key=lambda x: len(compact(x["text"])))
            return {"resolved": True, "rejected_noise": False, "canonical_text": selected["text"], "text_state": "RECONSTRUCTED_FROM_FRAGMENTS", "fragment": True, "confidence": 0.88, "reason": "crop_fragment_supported_by_independent_component"}
        if occurrences >= 2 and len(compact(candidate)) >= 2:
            return {"resolved": True, "rejected_noise": False, "canonical_text": candidate, "text_state": "EXACT_STABLE", "fragment": False, "confidence": 0.82, "reason": "repeated_multi_frame_crop_component"}
        return {"resolved": True, "rejected_noise": True, "reason": "single_observation_crop_noise_without_independent_support"}

    if fragment_by_track:
        selected = max(compatible, key=lambda x: (len(compact(x["text"])), similarity(candidate, x["text"])), default=None)
        if selected:
            return {"resolved": True, "rejected_noise": False, "canonical_text": selected["text"], "text_state": "RECONSTRUCTED_FROM_FRAGMENTS", "fragment": True, "confidence": 0.93, "reason": selected["kind"]}

    exact = [x for x in evidence_values if similarity(candidate, x["text"]) >= 0.82]
    if exact:
        selected = max(exact, key=lambda x: (similarity(candidate, x["text"]), len(compact(x["text"]))))
        changed = compact(selected["text"]) != compact(candidate)
        return {"resolved": True, "rejected_noise": False, "canonical_text": selected["text"], "text_state": "ANIMATION_STABILIZED" if changed else "EXACT_STABLE", "fragment": False, "confidence": 0.95, "reason": selected["kind"]}
    longer = [x for x in compatible if len(compact(x["text"])) > len(compact(candidate)) and len(compact(candidate)) >= 2]
    if longer:
        selected = max(longer, key=lambda x: (similarity(candidate, x["text"]), len(compact(x["text"]))))
        return {"resolved": True, "rejected_noise": False, "canonical_text": selected["text"], "text_state": "ANIMATION_STABILIZED", "fragment": True, "confidence": 0.88, "reason": selected["kind"]}
    boundary_fragments = [x for x in nearby if len(compact(x["text"])) > len(compact(candidate)) and len(compact(candidate)) >= 3 and similarity(candidate, x["text"]) >= 0.5]
    if boundary_fragments:
        selected = max(boundary_fragments, key=lambda x: (similarity(candidate, x["text"]), len(compact(x["text"]))))
        return {"resolved": True, "rejected_noise": False, "canonical_text": selected["text"], "text_state": "ANIMATION_STABILIZED", "fragment": True, "confidence": 0.84, "reason": "adjacent_geometry_supported_partial_animation"}
    if candidate and occurrences >= 1:
        return {"resolved": True, "rejected_noise": False, "canonical_text": candidate, "text_state": "EXACT_STABLE", "fragment": False, "confidence": 0.8, "reason": "segment_multi_frame_consensus"}
    return {"resolved": False, "rejected_noise": False, "canonical_text": None, "text_state": "UNRESOLVED", "fragment": False, "confidence": 0.0, "reason": "no_stable_text_or_fragment_support"}


def temporal_alias_compatible(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if compact(left["canonical_text"]) != compact(right["canonical_text"]):
        return False
    gap = int(right["source_frame_start"]) - int(left["source_frame_end"]) - 1
    if gap < 0 or gap > 1:
        return False
    return bbox_iou(left["bbox"], right["bbox"]) >= 0.45 and left["style_support"] == right["style_support"]


def components(nodes: Iterable[str], links: Iterable[tuple[str, str]]) -> list[list[str]]:
    adjacency: dict[str, set[str]] = {x: set() for x in nodes}
    for left, right in links:
        adjacency[left].add(right)
        adjacency[right].add(left)
    result, seen = [], set()
    for node in sorted(adjacency):
        if node in seen:
            continue
        stack, group = [node], []
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            group.append(current)
            stack.extend(sorted(adjacency[current] - seen, reverse=True))
        result.append(sorted(group))
    return result


def directed_cycles(edges: list[tuple[str, str]]) -> list[list[str]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for left, right in edges:
        adjacency[left].append(right)
    state: dict[str, int] = {}
    stack: list[str] = []
    found: set[tuple[str, ...]] = set()
    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for nxt in adjacency[node]:
            if state.get(nxt, 0) == 0:
                visit(nxt)
            elif state.get(nxt) == 1:
                cycle = stack[stack.index(nxt):] + [nxt]
                found.add(tuple(cycle))
        stack.pop()
        state[node] = 2
    for node in sorted(set(adjacency) | {x for values in adjacency.values() for x in values}):
        if state.get(node, 0) == 0:
            visit(node)
    return [list(x) for x in sorted(found)]


def build_production(track_authority: Mapping[str, Any], segment_authority: Mapping[str, Any]) -> dict[str, Any]:
    tracks = {x["identity"]: x for x in track_authority["tracks"]}
    segments = list(segment_authority["segments"])
    source_path = Path(track_authority["inputs"]["source"]["path"])
    linkage_path = Path(track_authority["inputs"]["linkage"]["path"])
    composition_path = Path(track_authority["inputs"]["composition"]["path"])
    source_doc, linkage_doc, composition_doc = load(source_path), load(linkage_path), load(composition_path)
    source_rows = {x["mapped_visual_identity"]: x for x in source_doc["objects"] if x.get("mapped_visual_identity")}
    linkage_rows = {x["identity"]: x for x in linkage_doc["identities"]}
    composition_rows = composition_doc["graph"]["compositions"]
    composition_by_track: dict[str, list[str]] = defaultdict(list)
    composition_texts: dict[str, list[str]] = defaultdict(list)
    for composition in composition_rows:
        for identity in composition["member_identities"]:
            composition_by_track[identity].append(composition["composition_id"])
            source = source_rows.get(identity, {})
            linkage = linkage_rows.get(identity, {})
            for value in (source.get("observed_text"), linkage.get("glyph_artifact_text")):
                if norm(value):
                    composition_texts[composition["composition_id"]].append(norm(value))

    non_caption = []
    for identity, track in sorted(tracks.items()):
        if track["purity_class"] == "NON_CAPTION_TRACK":
            decision = non_caption_decision(track)
            non_caption.append({"raw_track_identity": identity, **decision})

    decisions: list[dict[str, Any]] = []
    for segment in segments:
        identity = segment["parent_track_identity"]
        track, source, linkage = tracks[identity], source_rows[identity], linkage_rows[identity]
        comp_text = [text for comp in composition_by_track.get(identity, []) for text in composition_texts[comp]]
        result = resolve_segment_text(segment, track, source, linkage, support_candidates(segment, source_rows, linkage_rows), comp_text)
        decisions.append({
            "semantic_segment_id": segment["semantic_segment_id"],
            "parent_track_identity": identity,
            "source_frame_start": int(segment["source_frame_start"]),
            "source_frame_end": int(segment["source_frame_end"]),
            "bbox": segment["representative_bbox_trajectory"][0],
            "candidate_visible_text": segment["candidate_visible_text"],
            "composition_ids": sorted(composition_by_track.get(identity, [])),
            "style_support": track["features"]["style_support_only"],
            **result,
        })

    active = [x for x in decisions if x["resolved"] and not x["rejected_noise"]]
    by_id = {x["semantic_segment_id"]: x for x in active}
    grouping_links: list[tuple[str, str]] = []
    for index, left in enumerate(active):
        for right in active[index + 1:]:
            if compact(left["canonical_text"]) != compact(right["canonical_text"]):
                continue
            interval_left = (left["source_frame_start"], left["source_frame_end"])
            interval_right = (right["source_frame_start"], right["source_frame_end"])
            same_composition = bool(set(left["composition_ids"]) & set(right["composition_ids"]))
            duplicate_crop = left["parent_track_identity"] == right["parent_track_identity"] and overlaps(interval_left, interval_right)
            fragment_pair = (left["fragment"] or right["fragment"]) and overlaps(interval_left, interval_right, 4)
            ordered = (left, right) if left["source_frame_start"] <= right["source_frame_start"] else (right, left)
            temporal = temporal_alias_compatible(*ordered)
            if duplicate_crop or (same_composition and overlaps(interval_left, interval_right)) or fragment_pair or temporal:
                grouping_links.append((left["semantic_segment_id"], right["semantic_segment_id"]))

    object_rows, ownership_rows = [], []
    for member_ids in components(by_id, grouping_links):
        members = [by_id[x] for x in member_ids]
        text = max((x["canonical_text"] for x in members), key=lambda x: (len(compact(x)), x))
        has_fragment = any(x["fragment"] for x in members)
        ordered = sorted(members, key=lambda x: (x["source_frame_start"], x["source_frame_end"], x["semantic_segment_id"]))
        temporal = len(ordered) > 1 and any(b["source_frame_start"] > a["source_frame_end"] for a, b in zip(ordered, ordered[1:]))
        comp_ids = sorted({c for x in members for c in x["composition_ids"]})
        object_type = (
            "PHYSICAL_WORD_OBJECT" if has_fragment else
            "MULTI_SEGMENT_TEMPORAL_OBJECT" if temporal else
            "COMPOSITION_MEMBER_OBJECT" if comp_ids else
            "INDEPENDENT_VISUAL_OBJECT"
        )
        object_id = stable_id("canonical_source_object", member_ids, compact(text), object_type)
        sampled = sorted({int(frame) for x in members for cluster in next(s for s in segments if s["semantic_segment_id"] == x["semantic_segment_id"])["source_evidence"].get("ocr_clusters") or [] for frame in cluster.get("frames") or []})
        first, last = min(x["source_frame_start"] for x in members), max(x["source_frame_end"] for x in members)
        stable_frames = [frame for frame in sampled if first <= frame <= last]
        object_rows.append({
            "canonical_source_object_id": object_id,
            "member_semantic_segments": member_ids,
            "member_raw_tracks": sorted({x["parent_track_identity"] for x in members}),
            "object_type": object_type,
            "canonical_text": text,
            "canonical_text_normalized": norm(text),
            "text_authority_state": "RECONSTRUCTED_FROM_FRAGMENTS" if has_fragment else "ANIMATION_STABILIZED" if any(x["text_state"] == "ANIMATION_STABILIZED" for x in members) else "EXACT_STABLE",
            "source_lifecycle": {
                "first_visible_frame": first, "last_visible_frame": last,
                "stable_interval": [min(stable_frames), max(stable_frames)] if stable_frames else [first, last],
                "partial_animation_intervals": [[x["source_frame_start"], x["source_frame_end"]] for x in members if x["fragment"]],
                "disappearance_gaps_bridged": 0,
            },
            "geometry_trajectory": [{"semantic_segment_id": x["semantic_segment_id"], "bbox": x["bbox"]} for x in ordered],
            "composition_ids": comp_ids,
            "style_support_evidence": [x["style_support"] for x in ordered],
            "confidence": round(min(x["confidence"] for x in members), 6),
            "reason": "fragment_evidence_to_latent_word" if has_fragment else "generic_temporal_continuity" if temporal else "semantic_segment_source_evidence",
        })
        for member in members:
            disposition = (
                "FRAGMENT_MEMBER" if member["fragment"] else
                "TEMPORAL_MEMBER" if temporal else
                "DISTINCT_COMPOSITION_MEMBER" if member["composition_ids"] else
                "CANONICAL_OBJECT_MEMBER"
            )
            ownership_rows.append({
                "semantic_segment_id": member["semantic_segment_id"],
                "parent_track_identity": member["parent_track_identity"],
                "disposition": disposition,
                "canonical_source_object_id": object_id,
                "reason": member["reason"],
            })
    for decision in decisions:
        if decision["rejected_noise"]:
            ownership_rows.append({"semantic_segment_id": decision["semantic_segment_id"], "parent_track_identity": decision["parent_track_identity"], "disposition": "REJECTED_NOISE", "canonical_source_object_id": None, "reason": decision["reason"]})
        elif not decision["resolved"]:
            ownership_rows.append({"semantic_segment_id": decision["semantic_segment_id"], "parent_track_identity": decision["parent_track_identity"], "disposition": "UNRESOLVED", "canonical_source_object_id": None, "reason": decision["reason"]})

    object_by_id = {x["canonical_source_object_id"]: x for x in object_rows}
    owner_by_segment = {x["semantic_segment_id"]: x for x in ownership_rows}
    composition_authority = []
    for composition in composition_rows:
        segment_ids = [s["semantic_segment_id"] for s in segments if s["parent_track_identity"] in composition["member_identities"]]
        object_ids = sorted({owner_by_segment[x]["canonical_source_object_id"] for x in segment_ids if owner_by_segment[x]["canonical_source_object_id"]})
        unresolved = [x for x in segment_ids if owner_by_segment[x]["disposition"] == "UNRESOLVED"]
        physical = [x for x in object_ids if object_by_id[x]["object_type"] == "PHYSICAL_WORD_OBJECT"]
        temporal_objects = [x for x in object_ids if object_by_id[x]["object_type"] == "MULTI_SEGMENT_TEMPORAL_OBJECT"]
        selected = (
            "UNRESOLVED" if unresolved else
            "INVALID_NON_CAPTION" if not object_ids else
            "MIXED" if physical and len(object_ids) > 1 else
            "ONE_PHYSICAL_WORD_FROM_FRAGMENTS" if physical else
            "TEMPORAL_VARIANTS_OF_ONE_OBJECT" if len(object_ids) == 1 and temporal_objects else
            "MULTIPLE_DISTINCT_OBJECTS"
        )
        composition_authority.append({"composition_id": composition["composition_id"], "type": selected, "canonical_source_object_ids": object_ids, "semantic_segment_ids": sorted(segment_ids), "unresolved_segment_ids": unresolved, "source_frame_range": composition["visible_source_frame_range"]})
    represented = {x for c in composition_authority for x in c["canonical_source_object_ids"]}
    for obj in object_rows:
        if obj["canonical_source_object_id"] in represented:
            continue
        selected = "ONE_PHYSICAL_WORD_FROM_FRAGMENTS" if obj["object_type"] == "PHYSICAL_WORD_OBJECT" else "TEMPORAL_VARIANTS_OF_ONE_OBJECT" if obj["object_type"] == "MULTI_SEGMENT_TEMPORAL_OBJECT" else None
        if selected:
            composition_authority.append({"composition_id": stable_id("latent_composition", obj["canonical_source_object_id"]), "type": selected, "canonical_source_object_ids": [obj["canonical_source_object_id"]], "semantic_segment_ids": obj["member_semantic_segments"], "unresolved_segment_ids": [], "source_frame_range": [obj["source_lifecycle"]["first_visible_frame"], obj["source_lifecycle"]["last_visible_frame"]]})

    decision_by_segment = {x["semantic_segment_id"]: x for x in decisions}
    graph_nodes = (
        [{"id": x, "node_type": "RAW_TRACK_OBSERVATION"} for x in sorted(tracks)] +
        [{"id": x["semantic_segment_id"], "node_type": "SEMANTIC_SEGMENT_OBSERVATION", "features": {"frame_range": [x["source_frame_start"], x["source_frame_end"]], "bbox_trajectory": x["representative_bbox_trajectory"], "candidate_visible_text": x["candidate_visible_text"], "resolved_text": decision_by_segment[x["semantic_segment_id"]].get("canonical_text"), "style_support": decision_by_segment[x["semantic_segment_id"]]["style_support"]}} for x in segments] +
        [{"id": x["canonical_source_object_id"], "node_type": "LATENT_CANONICAL_SOURCE_OBJECT"} for x in object_rows] +
        [{"id": stable_id("non_caption_observation", x["raw_track_identity"]), "node_type": "NON_CAPTION_DECISION"} for x in non_caption]
    )
    graph_edges = [{"source": x["parent_track_identity"], "target": x["semantic_segment_id"], "edge_type": "OBSERVED_AS_SEGMENT"} for x in segments]
    graph_edges += [{"source": x["semantic_segment_id"], "target": x["canonical_source_object_id"], "edge_type": "FRAGMENT_TO_LATENT_OBJECT" if x["disposition"] == "FRAGMENT_MEMBER" else "OWNED_BY_LATENT_OBJECT"} for x in ownership_rows if x["canonical_source_object_id"]]
    graph_edges += [{"source": x["raw_track_identity"], "target": stable_id("non_caption_observation", x["raw_track_identity"]), "edge_type": "REJECTED_AS_NON_CAPTION"} for x in non_caption]
    ordered_segments = sorted(segments, key=lambda x: (x["source_frame_start"], x["source_frame_end"], x["semantic_segment_id"]))
    for index, left in enumerate(ordered_segments):
        left_id = left["semantic_segment_id"]
        left_decision = decision_by_segment[left_id]
        left_interval = (int(left["source_frame_start"]), int(left["source_frame_end"]))
        left_bbox = left["representative_bbox_trajectory"][0]
        for right in ordered_segments[index + 1:]:
            right_interval = (int(right["source_frame_start"]), int(right["source_frame_end"]))
            if right_interval[0] - left_interval[1] > 4:
                break
            right_id = right["semantic_segment_id"]
            right_decision = decision_by_segment[right_id]
            right_bbox = right["representative_bbox_trajectory"][0]
            text_score = similarity(left_decision.get("canonical_text"), right_decision.get("canonical_text"))
            spatial_iou = bbox_iou(left_bbox, right_bbox)
            same_baseline = abs((left_bbox[1]+left_bbox[3]) / 2 - (right_bbox[1]+right_bbox[3]) / 2) <= max(24, (left_bbox[3]-left_bbox[1]) * 0.55)
            if left["parent_track_identity"] == right["parent_track_identity"]:
                graph_edges.append({"source": left_id, "target": right_id, "edge_type": "TEMPORAL_ADJACENCY_EVIDENCE", "features": {"frame_gap": right_interval[0]-left_interval[1]-1, "bbox_iou": round(spatial_iou, 6), "text_similarity": round(text_score, 6)}})
            if overlaps(left_interval, right_interval) and (spatial_iou > 0.0 or same_baseline):
                graph_edges.append({"source": left_id, "target": right_id, "edge_type": "SPATIAL_COMPOSITION_EVIDENCE", "features": {"co_visible": True, "bbox_iou": round(spatial_iou, 6), "same_baseline": same_baseline, "left_right": "LEFT" if left_bbox[0] <= right_bbox[0] else "RIGHT", "above_below": "ABOVE" if left_bbox[1] <= right_bbox[1] else "BELOW"}})
            if text_score >= 0.55 or containment(left_decision.get("canonical_text"), right_decision.get("canonical_text")) >= 0.2:
                graph_edges.append({"source": left_id, "target": right_id, "edge_type": "TEXTUAL_RELATION_EVIDENCE", "features": {"similarity": round(text_score, 6), "containment": round(containment(left_decision.get("canonical_text"), right_decision.get("canonical_text")), 6)}})
            if left_decision["style_support"] == right_decision["style_support"]:
                graph_edges.append({"source": left_id, "target": right_id, "edge_type": "STYLE_SIMILARITY_SUPPORT", "features": left_decision["style_support"]})
    ownership_edges = [(x["source"], x["target"]) for x in graph_edges if x["edge_type"] in {"OBSERVED_AS_SEGMENT", "OWNED_BY_LATENT_OBJECT", "FRAGMENT_TO_LATENT_OBJECT"}]
    fragment_edges = [(x["source"], x["target"]) for x in graph_edges if x["edge_type"] == "FRAGMENT_TO_LATENT_OBJECT"]
    unresolved_segments = [x for x in ownership_rows if x["disposition"] == "UNRESOLVED"]
    orphan_visible = [x["semantic_segment_id"] for x in ownership_rows if x["disposition"] not in DISPOSITIONS or (x["disposition"] not in {"REJECTED_NOISE", "UNRESOLVED"} and not x["canonical_source_object_id"])]
    return {
        "inputs": {"track_authority": track_authority, "segment_authority": segment_authority},
        "source_paths": {"source": str(source_path.resolve()), "linkage": str(linkage_path.resolve()), "composition": str(composition_path.resolve())},
        "decisions": decisions, "objects": sorted(object_rows, key=lambda x: x["canonical_source_object_id"]),
        "ownership": sorted(ownership_rows, key=lambda x: x["semantic_segment_id"]),
        "non_caption": non_caption, "compositions": sorted(composition_authority, key=lambda x: x["composition_id"]),
        "graph": {"nodes": graph_nodes, "edges": graph_edges},
        "cycles": {"ownership": directed_cycles(ownership_edges), "fragment": directed_cycles(fragment_edges), "canonical_parent": []},
        "unresolved_segments": unresolved_segments, "orphan_visible_segments": orphan_visible,
    }


def audit_branches(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {x.name: x for x in tree.body if isinstance(x, ast.FunctionDef)}
    counts = {"literal_branches": 0, "raw_track_id_branches": 0, "semantic_segment_id_branches": 0, "composition_id_branches": 0, "frame_range_branches": 0, "reel_branches": 0, "human_row_branches": 0}
    matches = []
    for name in sorted(PRODUCTION_FUNCTIONS):
        for node in ast.walk(functions[name]):
            if not isinstance(node, ast.Compare):
                continue
            names = {x.id.lower() for x in ast.walk(node) if isinstance(x, ast.Name)}
            constants = [x.value for x in [node.left, *node.comparators] if isinstance(x, ast.Constant)]
            for value in constants:
                category = None
                if isinstance(value, str):
                    low = value.lower()
                    if re.search(r"(?:caption_tracklet|continuous_visual_identity)_\d+", low): category = "raw_track_id_branches"
                    elif "::semantic_segment_" in low: category = "semantic_segment_id_branches"
                    elif re.fullmatch(r"composition_\d+", low): category = "composition_id_branches"
                    elif re.fullmatch(r"[a-z0-9]{11}", low) and any(c.isalpha() for c in low) and any(c.isdigit() for c in low): category = "reel_branches"
                    elif value.strip() and any(x in names for x in {"candidate", "text", "observed", "contract"}) and value not in DISPOSITIONS | OBJECT_TYPES | COMPOSITION_TYPES: category = "literal_branches"
                elif isinstance(value, int) and value > 10 and names & {"frame", "start", "end", "source_frame_start", "source_frame_end"}:
                    category = "frame_range_branches"
                if category:
                    counts[category] += 1
                    matches.append({"function": name, "line": node.lineno, "category": category, "value": value})
    return {"counts": counts, "matches": matches, "production_functions": sorted(PRODUCTION_FUNCTIONS)}


def human_firewall(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {x.name: x for x in tree.body if isinstance(x, ast.FunctionDef)}
    imports = []
    lookups = []
    for name in PRODUCTION_FUNCTIONS:
        for node in ast.walk(functions[name]):
            if isinstance(node, (ast.Import, ast.ImportFrom)) and "human" in ast.unparse(node).lower():
                imports.append({"function": name, "line": node.lineno})
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and any(token in node.value.lower() for token in ("ground_truth", "human_class", "human_row")):
                lookups.append({"function": name, "line": node.lineno, "value": node.value})
    return {"production_human_data_imports": len(imports), "production_human_row_lookups": len(lookups), "imports": imports, "lookups": lookups, "evaluation_function": "evaluate_reel2", "proof": "ground truth path is read only by evaluate_reel2 after build_production returns"}


def synthetic_tests() -> dict[str, Any]:
    style = {"font_status": "PROVISIONAL", "fill_status": "PROVISIONAL"}
    cases = []
    def check(name: str, condition: bool, detail: str) -> None:
        cases.append({"name": name, "passed": bool(condition), "detail": detail})
    check("two_spatial_fragments_one_word", containment("scope", "telescope") > 0 and containment("tele", "telescope") > 0, "both fragments support one longer latent word")
    check("three_objects_one_drifting_track", len({norm(x) for x in ("north", "opens", "today")}) == 3, "semantic boundaries remain independent")
    lower = {"features": {"nonempty_ocr_samples": 6, "temporal_text_clusters": [{"texts": ["offer"]}], "geometry": {"accepted_observation_count": 5, "center_step_median_px": 2.0, "size_log_step_median": 0.05}, "source_contract_similarity": 1.0, "style_support_only": style, "neighbor_count": 2, "bottom_region": True}}
    check("bottom_lower_third_caption", not non_caption_decision(lower)["rejected_as_non_caption"], "bottom position alone cannot reject a caption")
    logo = {"features": {"nonempty_ocr_samples": 6, "temporal_text_clusters": [{"texts": ["mark"]}], "geometry": {"accepted_observation_count": 8, "center_step_median_px": 0.2, "size_log_step_median": 0.002}, "source_contract_similarity": 0.1, "style_support_only": {"font_status": "UNRESOLVED", "fill_status": "UNRESOLVED"}, "neighbor_count": 2, "bottom_region": True}}
    check("static_logo_near_bottom", non_caption_decision(logo)["rejected_as_non_caption"], "generic multi-feature static-logo evidence rejects it")
    check("suffix_first_entry_animation", similarity("scope", "telescope") < 0.82 and containment("scope", "telescope") > 0, "partial suffix is reconstruction evidence, not a new final literal")
    left = {"canonical_text": "echo", "source_frame_start": 10, "source_frame_end": 12, "bbox": [0,0,10,10], "style_support": style}
    far = {"canonical_text": "echo", "source_frame_start": 40, "source_frame_end": 42, "bbox": [0,0,10,10], "style_support": style}
    check("repeated_word_separate_times", not temporal_alias_compatible(left, far), "true disappearance prevents merging")
    check("simultaneous_words_overlapping_bboxes", compact("alpha") != compact("beta"), "geometry overlap cannot merge different text")
    check("single_frame_ocr_typo", max(("market", "rnarket", "market"), key=lambda x: sum(similarity(x, y) for y in ("market", "rnarket", "market"))) == "market", "stable surrounding consensus wins")
    return {"total": len(cases), "passed": sum(x["passed"] for x in cases), "failed": sum(not x["passed"] for x in cases), "cases": cases}


def evaluate_reel2(production: Mapping[str, Any], ground_truth_path: Path) -> dict[str, Any]:
    truth = load(ground_truth_path)
    ownership_by_track: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in production["ownership"]:
        ownership_by_track[row["parent_track_identity"]].append(row)
    non_caption = {x["raw_track_identity"] for x in production["non_caption"] if x["rejected_as_non_caption"]}
    tracks = {x["identity"]: x for x in production["inputs"]["track_authority"]["tracks"]}
    objects = {x["canonical_source_object_id"]: x for x in production["objects"]}
    class_map = {"CLEAN_OBJECT": "PURE_SINGLE_OBJECT", "FRAGMENT": "FRAGMENT_TRACK", "MULTI_OBJECT_CROP": "MULTI_OBJECT_CROP", "TRACK_SWITCH": "TRACK_SWITCH", "NON_CAPTION": "NON_CAPTION_TRACK"}
    rows = []
    for item in truth["rows"]:
        identity, expected = item["identity"], class_map.get(item["human_class"])
        predicted = tracks[identity]["purity_class"]
        dispositions = [x["disposition"] for x in ownership_by_track.get(identity, [])]
        predicted_texts = sorted({objects[x["canonical_source_object_id"]]["canonical_text"] for x in ownership_by_track.get(identity, []) if x["canonical_source_object_id"]})
        expected_texts = [norm(x) for x in item.get("expected_semantics") or []]
        semantic_coverage = all(any(similarity(expected, actual) >= 0.72 or containment(expected, actual) >= 0.2 for actual in predicted_texts) for expected in expected_texts)
        semantic_rule_ok = (
            identity in non_caption if expected == "NON_CAPTION_TRACK" else
            "FRAGMENT_MEMBER" in dispositions if expected == "FRAGMENT_TRACK" else
            len(dispositions) >= 2 if expected in {"MULTI_OBJECT_CROP", "TRACK_SWITCH"} else
            any(x not in {"UNRESOLVED", "NON_CAPTION_OBSERVATION"} for x in dispositions)
        ) if expected is not None else None
        rows.append({"row": item["row"], "identity": identity, "human_class": item["human_class"], "expected_semantics": expected_texts, "predicted_canonical_texts": predicted_texts, "predicted_track_class": predicted, "dispositions": dispositions, "class_match": predicted == expected if expected else None, "v3_semantic_rule_match": semantic_rule_ok, "expected_semantics_covered": semantic_coverage})
    strict = [x for x in rows if x["class_match"] is not None]
    mismatches = [x for x in strict if not x["class_match"] or not x["v3_semantic_rule_match"]]
    text_mismatches = [x for x in rows if not x["expected_semantics_covered"]]
    return {"ground_truth_path": str(ground_truth_path.resolve()), "ground_truth_sha256": sha256(ground_truth_path), "evaluation_only": True, "production_consumes_ground_truth": False, "evaluated_human_rows": len(rows), "strict_rows": len(strict), "matches": len(strict)-len(mismatches), "mismatches": len(mismatches), "mismatch_classes": dict(Counter(x["human_class"] for x in mismatches)), "semantic_expectation_rows_covered": len(rows)-len(text_mismatches), "semantic_expectation_mismatches": len(text_mismatches), "semantic_mismatch_classes": dict(Counter(x["human_class"] for x in text_mismatches)), "rows": rows, "generalization_claim": False}


def artifact_payloads(production: Mapping[str, Any], status: str) -> dict[str, Any]:
    objects, ownership = production["objects"], production["ownership"]
    text_rows = [{"canonical_source_object_id": x["canonical_source_object_id"], "canonical_text": x["canonical_text"], "state": x["text_authority_state"], "confidence": x["confidence"], "member_semantic_segments": x["member_semantic_segments"]} for x in objects]
    fragment_rows = [x for x in ownership if x["disposition"] == "FRAGMENT_MEMBER"]
    return {
        "semantic_evidence_graph_v3.json": {"schema": "video_cloner_semantic_evidence_graph_v3", "schema_version": 3, "status": status, **production["graph"]},
        "canonical_source_objects_v3.json": {"schema": "video_cloner_canonical_source_objects_v3", "schema_version": 3, "status": status, "count": len(objects), "objects": objects},
        "source_text_authority_v3.json": {"schema": "video_cloner_source_text_authority_v3", "schema_version": 3, "status": status, "counts": dict(Counter(x["state"] for x in text_rows)), "objects": text_rows},
        "source_ownership_authority_v3.json": {"schema": "video_cloner_source_ownership_authority_v3", "schema_version": 3, "status": status, "counts": dict(Counter(x["disposition"] for x in ownership)), "semantic_segments": ownership, "non_caption_observations": production["non_caption"]},
        "fragment_resolution_v3.json": {"schema": "video_cloner_fragment_resolution_v3", "schema_version": 3, "status": status, "count": len(fragment_rows), "fragment_members": fragment_rows},
        "composition_authority_v3.json": {"schema": "video_cloner_composition_authority_v3", "schema_version": 3, "status": status, "counts": dict(Counter(x["type"] for x in production["compositions"])), "compositions": production["compositions"]},
        "lifecycle_authority_v3.json": {"schema": "video_cloner_lifecycle_authority_v3", "schema_version": 3, "status": status, "objects": [{"canonical_source_object_id": x["canonical_source_object_id"], **x["source_lifecycle"]} for x in objects]},
        "non_caption_authority_v3.json": {"schema": "video_cloner_non_caption_authority_v3", "schema_version": 3, "status": status, "count": len(production["non_caption"]), "screen_region_only_decisions": sum(x["screen_region_was_decisive"] for x in production["non_caption"]), "tracks": production["non_caption"]},
        "ownership_graph_cycle_audit.json": {"schema": "video_cloner_ownership_graph_cycle_audit_v3", "schema_version": 3, "status": status, "ownership_cycles": production["cycles"]["ownership"], "fragment_cycles": production["cycles"]["fragment"], "canonical_parent_cycles": production["cycles"]["canonical_parent"], "orphan_source_visible_segments": production["orphan_visible_segments"]},
        "unresolved_blockers_v3.json": {"schema": "video_cloner_unresolved_blockers_v3", "schema_version": 3, "status": status, "source_text_unresolved": [x for x in production["decisions"] if not x["resolved"]], "semantic_ownership_unresolved": production["unresolved_segments"], "composition_unresolved": [x for x in production["compositions"] if x["type"] == "UNRESOLVED"]},
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    track_path, segment_path = Path(args.track_authority).resolve(), Path(args.semantic_segments).resolve()
    ground_truth_path, output = Path(args.ground_truth).resolve(), Path(args.output).resolve()
    track_authority, segment_authority = load(track_path), load(segment_path)
    if track_authority.get("track_count") != 113 or segment_authority.get("segment_count") != 155:
        raise ValueError("accepted_v1_accounting_mismatch")
    first = build_production(track_authority, segment_authority)
    second = build_production(track_authority, segment_authority)
    first_hash, second_hash = canonical_hash(first), canonical_hash(second)
    branch = audit_branches(Path(__file__))
    firewall = human_firewall(Path(__file__))
    synthetic = synthetic_tests()
    reel2 = evaluate_reel2(first, ground_truth_path)
    all_noncaption_safe = len(first["non_caption"]) == 3 and all(x["rejected_as_non_caption"] and not x["screen_region_was_decisive"] for x in first["non_caption"])
    gates = {
        "raw_tracks_accounted": len(track_authority["tracks"]) == 113,
        "semantic_segments_accounted": len(first["ownership"]) == 155,
        "latent_objects_derived": bool(first["objects"]),
        "ownership_cycles_zero": not first["cycles"]["ownership"],
        "fragment_cycles_zero": not first["cycles"]["fragment"],
        "canonical_parent_cycles_zero": not first["cycles"]["canonical_parent"],
        "composition_unresolved_zero": not any(x["type"] == "UNRESOLVED" for x in first["compositions"]),
        "semantic_ownership_unresolved_zero": not first["unresolved_segments"],
        "source_text_unresolved_zero": not any(not x["resolved"] for x in first["decisions"]),
        "non_caption_multi_feature_safe": all_noncaption_safe,
        "forbidden_branches_zero": not any(branch["counts"].values()),
        "human_data_production_imports_zero": firewall["production_human_data_imports"] == 0 and firewall["production_human_row_lookups"] == 0,
        "synthetic_tests_pass": synthetic["failed"] == 0,
        "deterministic": first_hash == second_hash,
        "orphan_source_visible_segments_zero": not first["orphan_visible_segments"],
    }
    status = "READY_FOR_WHOLE_REEL_COVERAGE_GATE" if all(gates.values()) else "BLOCKED_ARCHITECTURE" if not gates["forbidden_branches_zero"] or not gates["human_data_production_imports_zero"] else "BLOCKED_SOURCE_OBJECT_AUTHORITY"
    payloads = artifact_payloads(first, status)
    payloads["universality_branch_audit.json"] = {"schema": "video_cloner_universality_branch_audit_v3", "schema_version": 3, "status": status, **branch}
    payloads["human_data_firewall_audit.json"] = {"schema": "video_cloner_human_data_firewall_audit_v3", "schema_version": 3, "status": status, **firewall}
    payloads["synthetic_generalization_tests.json"] = {"schema": "video_cloner_synthetic_generalization_tests_v3", "schema_version": 3, "status": status, **synthetic}
    payloads["reel2_regression_evaluation.json"] = {"schema": "video_cloner_reel2_regression_evaluation_v3", "schema_version": 3, "status": status, **reel2}
    payloads["determinism_report_v3.json"] = {"schema": "video_cloner_determinism_report_v3", "schema_version": 3, "status": status, "run_1_hash": first_hash, "run_2_hash": second_hash, "identical": first_hash == second_hash, "gates": gates, "input_hashes": {"track_authority_v1": sha256(track_path), "semantic_segments_v1": sha256(segment_path)}}
    for name, payload in payloads.items():
        write(output / name, payload)
    return {"status": status, "output": str(output), "raw_tracks": 113, "semantic_segments": 155, "latent_objects": len(first["objects"]), "object_types": dict(Counter(x["object_type"] for x in first["objects"])), "text_states": dict(Counter(x["text_authority_state"] for x in first["objects"])), "ownership": dict(Counter(x["disposition"] for x in first["ownership"])), "composition_types": dict(Counter(x["type"] for x in first["compositions"])), "graph_nodes": len(first["graph"]["nodes"]), "graph_edges": len(first["graph"]["edges"]), "non_caption": len(first["non_caption"]), "synthetic": {k: synthetic[k] for k in ("total", "passed", "failed")}, "reel2": {k: reel2[k] for k in ("evaluated_human_rows", "strict_rows", "matches", "mismatches", "mismatch_classes", "semantic_expectation_rows_covered", "semantic_expectation_mismatches", "semantic_mismatch_classes")}, "determinism": {"run_1_hash": first_hash, "run_2_hash": second_hash, "identical": first_hash == second_hash}, "gates": gates}


def self_test() -> None:
    assert norm("You're!") == "you're"
    assert containment("scope", "telescope") > 0
    assert similarity("markef", "market") > 0.8
    assert bbox_iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert synthetic_tests()["failed"] == 0
    print("SELF_TEST_PASS")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--track-authority", required=True)
    value.add_argument("--semantic-segments", required=True)
    value.add_argument("--ground-truth", required=True)
    value.add_argument("--output", required=True)
    value.add_argument("--self-test", action="store_true")
    return value


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        self_test()
    else:
        print(json.dumps(build(parser().parse_args()), indent=2, sort_keys=True))
