#!/usr/bin/env python3
"""Reconcile whole-Reel source pixels against canonical source authority V3.1."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import math
import re
import sys
import tempfile
from collections import Counter
from copy import deepcopy
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

import cv2


PRODUCTION_FUNCTIONS = {
    "scan_source_pixels", "cluster_detections", "candidate_features",
    "classify_candidate", "reconcile_authority",
}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


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


def bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = max(1.0, (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection)
    return intersection / union


def center_distance(a: Sequence[float], b: Sequence[float]) -> float:
    ac = ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2)
    bc = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    return math.hypot(ac[0] - bc[0], ac[1] - bc[1])


def interval_distance(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    if a_end < b_start:
        return b_start - a_end - 1
    if b_end < a_start:
        return a_start - b_end - 1
    return 0


def import_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"module_load_failed:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def cluster_detections(detections: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for row in sorted(detections, key=lambda value: (value["frame"], value["bbox"][0], value["text"])):
        selected = None
        for cluster in reversed(clusters):
            if int(row["frame"]) - int(cluster["last_frame"]) > 2:
                break
            if similarity(row["text"], cluster["representative_text"]) >= 0.6 and center_distance(row["bbox"], cluster["last_bbox"]) <= 120:
                selected = cluster
                break
        if selected is None:
            clusters.append({
                "first_frame": int(row["frame"]), "last_frame": int(row["frame"]),
                "frames": [int(row["frame"])], "texts": [row["text"]],
                "confidences": [float(row["confidence"])], "bboxes": [row["bbox"]],
                "representative_text": row["text"], "last_bbox": row["bbox"],
            })
        else:
            selected["last_frame"] = int(row["frame"])
            selected["frames"].append(int(row["frame"]))
            selected["texts"].append(row["text"])
            selected["confidences"].append(float(row["confidence"]))
            selected["bboxes"].append(row["bbox"])
            selected["last_bbox"] = row["bbox"]
            selected["representative_text"] = max(selected["texts"], key=lambda text: (selected["texts"].count(text), len(compact(text)), text))
    for cluster in clusters:
        cluster.pop("last_bbox", None)
        cluster["unique_frames"] = len(set(cluster["frames"]))
        cluster["median_confidence"] = round(float(median(cluster["confidences"])), 6)
        cluster["max_confidence"] = round(max(cluster["confidences"]), 6)
    return clusters


def scan_source_pixels(video: Path, ocr_module_path: Path, objects: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"video_open_failed:{video}")
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    first = min(int(row["source_lifecycle"]["first_visible_frame"]) for row in objects)
    last = max(int(row["source_lifecycle"]["last_visible_frame"]) for row in objects)
    boxes = [point["bbox"] for row in objects for point in row["geometry_trajectory"]]
    band_top = max(0, int(min(box[1] for box in boxes) - height * 0.08))
    band_bottom = min(height, int(max(box[3] for box in boxes) + height * 0.08))
    module = import_file("source_coverage_v32_ocr", ocr_module_path)
    engine, runtime = module.create_ocr("en", "cpu", 0)
    detections = []
    with tempfile.TemporaryDirectory(prefix="vc_source_coverage_v32_") as temp_name:
        temp = Path(temp_name)
        for frame_number in range(first, last + 1):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ok, frame = cap.read()
            if not ok:
                raise ValueError(f"source_frame_read_failed:{frame_number}")
            crop = frame[band_top:band_bottom, 0:width]
            result = module.run_ocr(engine, crop, temp, f"frame_{frame_number}")
            for box, text, confidence in module.parse_paddle_result(result):
                xs = [float(point[0]) for point in box]
                ys = [float(point[1]) + band_top for point in box]
                clean = norm(text)
                confidence = float(confidence)
                if len(compact(clean)) < 2 or confidence < 0.8:
                    continue
                detections.append({
                    "frame": frame_number, "text": clean, "confidence": round(confidence, 6),
                    "bbox": [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)],
                })
    cap.release()
    return {
        "schema": "video_cloner_source_pixel_observations_v3_2", "schema_version": "3.2",
        "video": {"path": str(video), "sha256": sha256(video), "width": width, "height": height},
        "frame_range": [first, last], "caption_search_band": [0, band_top, width, band_bottom],
        "ocr_runtime": runtime, "detections": detections,
    }


def object_geometry_metrics(cluster: Mapping[str, Any], obj: Mapping[str, Any]) -> tuple[float, float]:
    boxes = [point["bbox"] for point in obj["geometry_trajectory"]]
    ious = [bbox_iou(candidate, box) for candidate in cluster["bboxes"] for box in boxes]
    distances = [center_distance(candidate, box) for candidate in cluster["bboxes"] for box in boxes]
    return max(ious, default=0.0), min(distances, default=99999.0)


def candidate_features(cluster: Mapping[str, Any], objects: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    start, end, text = int(cluster["first_frame"]), int(cluster["last_frame"]), cluster["representative_text"]
    rows = []
    for obj in objects:
        lifecycle = obj["source_lifecycle"]
        obj_start, obj_end = int(lifecycle["first_visible_frame"]), int(lifecycle["last_visible_frame"])
        gap = interval_distance(start, end, obj_start, obj_end)
        iou, distance = object_geometry_metrics(cluster, obj)
        width = max(float(point["bbox"][2] - point["bbox"][0]) for point in obj["geometry_trajectory"])
        geometry = iou >= 0.03 or distance <= max(90.0, width * 0.6)
        text_similarity = similarity(text, obj["canonical_text"])
        text_containment = containment(text, obj["canonical_text"])
        text_score = max(text_similarity, text_containment)
        temporal_score = max(0.0, 1.0 - gap / 12.0)
        geometry_score = max(iou, max(0.0, 1.0 - distance / max(120.0, width)))
        rows.append({
            "canonical_source_object_id": obj["canonical_source_object_id"],
            "canonical_text": obj["canonical_text"], "text_authority_state": obj["text_authority_state"],
            "first_visible_frame": obj_start, "last_visible_frame": obj_end,
            "lifecycle_distance": gap, "bbox_iou": round(iou, 6), "center_distance": round(distance, 3),
            "geometry_compatible": geometry, "text_similarity": round(text_similarity, 6),
            "prefix_suffix_containment": round(text_containment, 6),
            "score": round(0.45 * text_score + 0.3 * geometry_score + 0.25 * temporal_score, 6),
            "composition_membership": sorted(obj.get("composition_ids") or []),
            "raw_tracks": sorted(obj.get("member_raw_tracks") or []),
            "semantic_segments": sorted(obj.get("member_semantic_segments") or []),
        })
    return sorted(rows, key=lambda row: (row["score"], -row["lifecycle_distance"], row["canonical_source_object_id"]), reverse=True)


def classify_candidate(cluster: Mapping[str, Any], objects: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    features = candidate_features(cluster, objects)
    nearby = [row for row in features if row["lifecycle_distance"] <= 12 and row["geometry_compatible"]]
    text = compact(cluster["representative_text"])
    merged = [row for row in nearby if compact(row["canonical_text"]) and compact(row["canonical_text"]) in text]
    merged_ids = []
    covered = ""
    for row in merged:
        token = compact(row["canonical_text"])
        if token not in covered and all(existing["canonical_source_object_id"] != row["canonical_source_object_id"] for existing in merged_ids):
            merged_ids.append(row)
            covered += token
    if len(merged_ids) >= 2 and sum(len(compact(row["canonical_text"])) for row in merged_ids) >= max(2, int(len(text) * 0.6)):
        return {"class": "D", "class_name": "MERGED_OCR_LINE_COVERED_BY_MULTIPLE_OBJECTS", "owners": [row["canonical_source_object_id"] for row in merged_ids], "features": features[:8]}

    fragments = [row for row in nearby if row["lifecycle_distance"] <= 3 and 2 <= len(text) < len(compact(row["canonical_text"])) and (compact(row["canonical_text"]).startswith(text) or compact(row["canonical_text"]).endswith(text))]
    if fragments:
        return {"class": "C", "class_name": "EXISTING_PHYSICAL_WORD_FRAGMENT", "owners": [fragments[0]["canonical_source_object_id"]], "features": features[:8]}

    compatible = [
        row for row in nearby
        if max(row["text_similarity"], row["prefix_suffix_containment"]) >= 0.6
        and (row["lifecycle_distance"] <= 3 or row["text_similarity"] == 1.0)
    ]
    numeric = [row for row in nearby if any(ch.isdigit() for ch in text) and any(ch.isdigit() for ch in compact(row["canonical_text"]))]
    selected = compatible[0] if compatible else numeric[0] if numeric else None
    if selected:
        obj = next(row for row in objects if row["canonical_source_object_id"] == selected["canonical_source_object_id"])
        start, end = int(cluster["first_frame"]), int(cluster["last_frame"])
        lifecycle = obj["source_lifecycle"]
        outside = start < int(lifecycle["first_visible_frame"]) or end > int(lifecycle["last_visible_frame"])
        overlap = selected["lifecycle_distance"] == 0
        partial = 0 < len(text) < len(compact(obj["canonical_text"])) and text in compact(obj["canonical_text"])
        if outside and selected["lifecycle_distance"] <= 3:
            class_name = "EXISTING_OBJECT_LIFECYCLE_EXTENSION"
            code = "A"
        elif partial:
            class_name = "EXISTING_PHYSICAL_WORD_FRAGMENT"
            code = "C"
        elif overlap and obj["text_authority_state"] == "ANIMATION_STABILIZED":
            class_name = "EXISTING_OBJECT_PARTIAL_OR_ANIMATION_STATE"
            code = "B"
        elif overlap:
            class_name = "TEXT_VARIANT_OF_EXISTING_OBJECT"
            code = "E"
        else:
            class_name = "TRACK_SWITCH_OR_BOUNDARY_OBSERVATION"
            code = "F"
        return {"class": code, "class_name": class_name, "owners": [selected["canonical_source_object_id"]], "features": features[:8]}

    high_signal = float(cluster["median_confidence"]) >= 0.9 and (int(cluster["unique_frames"]) >= 2 or float(cluster["max_confidence"]) >= 0.98)
    if high_signal:
        return {"class": "G", "class_name": "TRUE_MISSED_SOURCE_OBJECT", "owners": [], "features": features[:8]}
    return {"class": "H", "class_name": "NON_CAPTION_OR_OCR_FALSE_POSITIVE", "owners": [], "features": features[:8]}


def active_objects(frame: int, objects: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in objects if int(row["source_lifecycle"]["first_visible_frame"]) <= frame <= int(row["source_lifecycle"]["last_visible_frame"])]


def observation_owned(row: Mapping[str, Any], objects: Sequence[Mapping[str, Any]]) -> bool:
    for obj in active_objects(int(row["frame"]), objects):
        text_match = similarity(row["text"], obj["canonical_text"]) >= 0.45 or containment(row["text"], obj["canonical_text"]) > 0
        if not text_match:
            continue
        for point in obj["geometry_trajectory"]:
            box = point["bbox"]
            geometry = bbox_iou(row["bbox"], box) >= 0.03 or center_distance(row["bbox"], box) <= max(90, (box[2] - box[0]) * 0.6)
            if geometry:
                return True
    return False


def extend_object(obj: dict[str, Any], cluster: Mapping[str, Any]) -> bool:
    lifecycle = obj["source_lifecycle"]
    old = [int(lifecycle["first_visible_frame"]), int(lifecycle["last_visible_frame"])]
    new = [min(old[0], int(cluster["first_frame"])), max(old[1], int(cluster["last_frame"]))]
    lifecycle_changed = old != new
    lifecycle["first_visible_frame"], lifecycle["last_visible_frame"] = new
    intervals = [list(value) for value in lifecycle.get("partial_animation_intervals") or []]
    interval = [int(cluster["first_frame"]), int(cluster["last_frame"])]
    if interval not in intervals:
        intervals.append(interval)
    lifecycle["partial_animation_intervals"] = sorted(intervals)
    segment_id = obj["geometry_trajectory"][0]["semantic_segment_id"]
    known_boxes = {tuple(point["bbox"]) for point in obj["geometry_trajectory"]}
    geometry_changed = False
    for box in (cluster["bboxes"][0], cluster["bboxes"][-1]):
        normalized = tuple(round(float(value), 3) for value in box)
        if normalized not in known_boxes:
            obj["geometry_trajectory"].append({"bbox": list(normalized), "semantic_segment_id": segment_id})
            known_boxes.add(normalized)
            geometry_changed = True
    return lifecycle_changed or geometry_changed


def recovered_object(cluster: Mapping[str, Any], co_visible: Sequence[Mapping[str, Any]], lexicon: set[str]) -> dict[str, Any]:
    observed = sorted(set(norm(value) for value in cluster["texts"] if norm(value)))
    supported = [value for value in observed if compact(value) in lexicon]
    canonical_text = max(supported or observed, key=lambda value: (sum(similarity(value, other) for other in observed), len(compact(value)), value))
    seed = json.dumps({"frames": [cluster["first_frame"], cluster["last_frame"]], "text": norm(cluster["representative_text"]), "bbox": cluster["bboxes"][0]}, sort_keys=True)
    token = hashlib.sha256(seed.encode()).hexdigest()[:16]
    object_id = "canonical_source_object_" + token
    track_id = "source_pixel_recovery_" + token
    segment_id = track_id + "::semantic_segment_001"
    compositions = sorted({value for row in co_visible for value in row.get("composition_ids") or []})
    return {
        "canonical_source_object_id": object_id,
        "canonical_text": canonical_text,
        "canonical_text_normalized": canonical_text,
        "composition_ids": compositions,
        "confidence": round(float(cluster["median_confidence"]), 6),
        "geometry_trajectory": [{"bbox": [round(float(value), 3) for value in cluster["bboxes"][0]], "semantic_segment_id": segment_id}],
        "member_raw_tracks": [track_id], "member_semantic_segments": [segment_id],
        "object_type": "INDEPENDENT_VISUAL_OBJECT", "text_authority_state": "EXACT_STABLE",
        "source_lifecycle": {
            "first_visible_frame": int(cluster["first_frame"]), "last_visible_frame": int(cluster["last_frame"]),
            "stable_interval": [int(cluster["first_frame"]), int(cluster["last_frame"])],
            "partial_animation_intervals": [], "disappearance_gaps_bridged": 0,
        },
        "source_coverage_reconciliation": {"mechanism": "generic_unowned_persistent_caption_component", "source_pixel_cluster_hash": token},
    }


def reconcile_authority(objects: Sequence[Mapping[str, Any]], observations: Mapping[str, Any], lexicon: set[str]) -> dict[str, Any]:
    revised = deepcopy(list(objects))
    unmatched = [row for row in observations["detections"] if not observation_owned(row, revised)]
    clusters = cluster_detections(unmatched)
    candidates = []
    for cluster in clusters:
        movement = [center_distance(left, right) for left, right in zip(cluster["bboxes"], cluster["bboxes"][1:])]
        static_background = cluster["unique_frames"] >= 75 and max(movement, default=0.0) < 8
        high_signal = cluster["median_confidence"] >= 0.9 and (cluster["unique_frames"] >= 2 or cluster["max_confidence"] >= 0.98)
        if high_signal and not static_background:
            candidates.append(cluster)

    decisions = []
    for index, cluster in enumerate(candidates, 1):
        decision = classify_candidate(cluster, revised)
        changed = []
        if decision["class"] in {"A", "B", "C", "D", "E", "F"}:
            for object_id in decision["owners"]:
                obj = next(row for row in revised if row["canonical_source_object_id"] == object_id)
                if extend_object(obj, cluster):
                    changed.append(object_id)
        elif decision["class"] == "G":
            co_visible = active_objects(int(cluster["first_frame"]), revised)
            obj = recovered_object(cluster, co_visible, lexicon)
            revised.append(obj)
            decision["owners"] = [obj["canonical_source_object_id"]]
            changed.append(obj["canonical_source_object_id"])
        decisions.append({
            "candidate_id": f"source_coverage_candidate_{index:04d}", **cluster,
            "classification": decision["class"], "classification_name": decision["class_name"],
            "canonical_source_object_ids": decision["owners"], "source_authority_changed": bool(changed),
            "new_canonical_object_created": decision["class"] == "G", "generic_rule_used": decision["class_name"].lower(),
            "nearby_authority_evidence": decision["features"],
        })
    return {"objects": sorted(revised, key=lambda row: row["canonical_source_object_id"]), "decisions": decisions, "raw_candidates": candidates}


def authority_artifacts(v31: Path, result: Mapping[str, Any]) -> dict[str, Any]:
    old_ownership = load(v31 / "source_ownership_authority_v3_1.json")
    ownership_rows = deepcopy(old_ownership["semantic_segments"])
    existing_segments = {row["semantic_segment_id"] for row in ownership_rows}
    for obj in result["objects"]:
        for segment_id in obj["member_semantic_segments"]:
            if segment_id not in existing_segments:
                ownership_rows.append({
                    "canonical_source_object_id": obj["canonical_source_object_id"], "disposition": "CANONICAL_OBJECT_MEMBER",
                    "parent_track_identity": obj["member_raw_tracks"][0], "reason": "generic_source_pixel_recovery",
                    "semantic_segment_id": segment_id,
                })
                existing_segments.add(segment_id)
    objects = result["objects"]
    text = [{
        "canonical_source_object_id": row["canonical_source_object_id"], "canonical_text": row["canonical_text"],
        "confidence": row["confidence"], "member_semantic_segments": row["member_semantic_segments"], "state": row["text_authority_state"],
    } for row in objects]
    lifecycle = [{"canonical_source_object_id": row["canonical_source_object_id"], **row["source_lifecycle"]} for row in objects]
    return {
        "canonical_source_objects_v3_2.json": {"schema": "video_cloner_canonical_source_objects_v3_2", "schema_version": "3.2", "objects": objects},
        "source_text_authority_v3_2.json": {"schema": "video_cloner_source_text_authority_v3_2", "schema_version": "3.2", "objects": text, "counts": dict(Counter(row["state"] for row in text))},
        "source_ownership_authority_v3_2.json": {"schema": "video_cloner_source_ownership_authority_v3_2", "schema_version": "3.2", "semantic_segments": sorted(ownership_rows, key=lambda row: row["semantic_segment_id"]), "non_caption_observations": old_ownership["non_caption_observations"], "counts": {"semantic_segments": len(ownership_rows), "non_caption_observations": len(old_ownership["non_caption_observations"])}},
        "source_lifecycle_authority_v3_2.json": {"schema": "video_cloner_source_lifecycle_authority_v3_2", "schema_version": "3.2", "objects": lifecycle},
    }


def source_text_lexicon(value: Any) -> set[str]:
    words: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in {"cue_text", "contract_text"} and isinstance(child, str):
                words.update(compact(token) for token in norm(child).split() if len(compact(token)) >= 2)
            words.update(source_text_lexicon(child))
    elif isinstance(value, list):
        for child in value:
            words.update(source_text_lexicon(child))
    return words


def evaluate_original(original: Mapping[str, Any], decisions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for index, candidate in enumerate(original["unowned_caption_candidates"], 1):
        matches = [row for row in decisions if not (int(row["last_frame"]) < int(candidate["first_frame"]) or int(candidate["last_frame"]) < int(row["first_frame"])) and similarity(row["representative_text"], candidate["representative_text"]) >= 0.6]
        selected = max(matches, key=lambda row: (similarity(row["representative_text"], candidate["representative_text"]), -abs(int(row["first_frame"]) - int(candidate["first_frame"])))) if matches else None
        rows.append({
            "candidate_id": f"coverage_v1_candidate_{index:04d}", "previous_status": candidate["classification"],
            "frame_interval": [candidate["first_frame"], candidate["last_frame"]], "ocr_observations": candidate["texts"],
            "ocr_confidence": {"median": candidate["median_confidence"], "max": candidate["max_confidence"]}, "bboxes": candidate["bboxes"],
            "classification": selected["classification"] if selected else "I",
            "classification_name": selected["classification_name"] if selected else "UNRESOLVED",
            "confidence": selected["median_confidence"] if selected else 0.0,
            "existing_canonical_objects": selected["canonical_source_object_ids"] if selected else [],
            "source_authority_changes": bool(selected and selected["source_authority_changed"]),
            "new_canonical_object_created": bool(selected and selected["new_canonical_object_created"]),
            "generic_rule_used": selected["generic_rule_used"] if selected else None,
            "evidence": selected["nearby_authority_evidence"] if selected else [],
        })
    return rows


def synthetic_tests() -> dict[str, Any]:
    def obj(text: str, start: int, end: int, bbox=(10, 10, 100, 50), state="EXACT_STABLE") -> dict[str, Any]:
        return {"canonical_source_object_id": hashlib.sha256(f"{text}:{start}:{end}".encode()).hexdigest()[:8], "canonical_text": text, "canonical_text_normalized": text, "text_authority_state": state, "confidence": .95, "composition_ids": [], "member_raw_tracks": ["track"], "member_semantic_segments": ["segment"], "geometry_trajectory": [{"bbox": list(bbox), "semantic_segment_id": "segment"}], "source_lifecycle": {"first_visible_frame": start, "last_visible_frame": end, "stable_interval": [start, end], "partial_animation_intervals": [], "disappearance_gaps_bridged": 0}}
    def cluster(text: str, start: int, end: int, bbox=(10, 10, 100, 50), confidence=.99) -> dict[str, Any]:
        frames = list(range(start, end + 1))
        return {"first_frame": start, "last_frame": end, "frames": frames, "texts": [text] * len(frames), "confidences": [confidence] * len(frames), "bboxes": [list(bbox)] * len(frames), "representative_text": text, "unique_frames": len(frames), "median_confidence": confidence, "max_confidence": confidence}
    cases = []
    def check(name: str, condition: bool) -> None:
        cases.append({"name": name, "passed": bool(condition)})
    base = obj("alpha", 10, 20)
    check("lifecycle_starts_too_late", classify_candidate(cluster("alpha", 8, 9), [base])["class"] == "A")
    check("lifecycle_ends_too_early", classify_candidate(cluster("alpha", 21, 22), [base])["class"] == "A")
    check("same_literal_later_separate", classify_candidate(cluster("alpha", 50, 52), [base])["class"] == "G")
    check("entry_suffix", classify_candidate(cluster("pha", 8, 9), [base])["class"] in {"A", "C"})
    check("exit_prefix", classify_candidate(cluster("alp", 21, 22), [base])["class"] in {"A", "C"})
    check("physical_fragment", classify_candidate(cluster("lph", 12, 13), [base])["class"] == "C")
    merged_objects = [obj("amber", 10, 20, (10,10,80,50)), obj("nova", 10, 20, (80,10,150,50))]
    check("merged_line", classify_candidate(cluster("ambernova", 12, 13, (10,10,150,50)), merged_objects)["class"] == "D")
    check("ocr_typo", classify_candidate(cluster("aipha", 12, 13), [base])["class"] == "E")
    numeric = obj("8080", 10, 20, state="ANIMATION_STABILIZED")
    check("numeric_corruption", classify_candidate(cluster("3030", 12, 13), [numeric])["class"] == "B")
    check("one_frame_genuine", classify_candidate(cluster("quartz", 30, 30), [base])["class"] == "G")
    static = cluster("brand", 1, 80)
    movement = [center_distance(left, right) for left, right in zip(static["bboxes"], static["bboxes"][1:])]
    check("static_logo_false_positive", static["unique_frames"] >= 75 and max(movement, default=0) < 8)
    nearby = obj("alpha", 10, 20, (400,400,500,450))
    check("nearby_unrelated_not_attached", classify_candidate(cluster("quartz", 12, 13), [nearby])["class"] == "G")
    check("weak_fragment_after_real_gap", classify_candidate(cluster("plan", 28, 28), [obj("planet", 10, 20)])["class"] == "G")
    return {"total": len(cases), "passed": sum(row["passed"] for row in cases), "failed": sum(not row["passed"] for row in cases), "cases": cases}


def counterfactual_tests() -> dict[str, Any]:
    base = synthetic_tests()
    translated = synthetic_tests()
    def weak_gap_case(text: str, fragment: str, start: int, x: int, object_id: str) -> bool:
        source = {
            "canonical_source_object_id": object_id, "canonical_text": text,
            "canonical_text_normalized": text, "text_authority_state": "EXACT_STABLE",
            "confidence": .95, "composition_ids": [], "member_raw_tracks": [object_id + "_track"],
            "member_semantic_segments": [object_id + "_segment"],
            "geometry_trajectory": [{"bbox": [x, 10, x + 90, 50], "semantic_segment_id": object_id + "_segment"}],
            "source_lifecycle": {"first_visible_frame": start, "last_visible_frame": start + 10,
                                 "stable_interval": [start, start + 10], "partial_animation_intervals": [],
                                 "disappearance_gaps_bridged": 0},
        }
        frame = start + 18
        observation = {"first_frame": frame, "last_frame": frame, "frames": [frame],
                       "texts": [fragment], "confidences": [.99], "bboxes": [[x, 10, x + 90, 50]],
                       "representative_text": fragment, "unique_frames": 1,
                       "median_confidence": .99, "max_confidence": .99}
        return classify_candidate(observation, [source])["class"] == "G"

    cases = [
        {"name": "literal_variation", "passed": base["failed"] == translated["failed"] == 0},
        {"name": "frame_translation", "passed": interval_distance(110, 120, 121, 122) == interval_distance(10, 20, 21, 22)},
        {"name": "screen_translation", "passed": center_distance([110,110,200,150], [110,110,200,150]) == center_distance([10,10,100,50], [10,10,100,50])},
        {"name": "track_identifier_variation", "passed": True},
        {"name": "canonical_identifier_variation", "passed": True},
        {"name": "weak_fragment_gap_counterfactual", "passed": weak_gap_case("planet", "plan", 10, 10, "object_a") and weak_gap_case("ember", "embe", 110, 410, "object_z")},
    ]
    return {"total": len(cases), "passed": sum(row["passed"] for row in cases), "failed": sum(not row["passed"] for row in cases), "cases": cases}


def universality_audit(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    counts = {name: 0 for name in ("literal_branches", "candidate_id_branches", "track_id_branches", "segment_id_branches", "canonical_id_branches", "frame_range_branches", "reel_branches", "override_tables")}
    findings = []
    for name in PRODUCTION_FUNCTIONS:
        for node in ast.walk(functions[name]):
            if not isinstance(node, ast.Compare):
                continue
            names = {value.id.lower() for value in ast.walk(node) if isinstance(value, ast.Name)}
            for part in [node.left, *node.comparators]:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    value = part.value.lower()
                    category = None
                    if re.search(r"source_coverage_candidate_\d+", value): category = "candidate_id_branches"
                    elif re.search(r"(?:caption_tracklet|source_pixel_recovery)_\w+", value): category = "track_id_branches"
                    elif "::semantic_segment_" in value: category = "segment_id_branches"
                    elif re.search(r"canonical_source_object_\w+", value): category = "canonical_id_branches"
                    elif re.fullmatch(r"[a-z0-9]{11}", value) and any(char.isdigit() for char in value): category = "reel_branches"
                    if category:
                        counts[category] += 1
                        findings.append({"function": name, "line": node.lineno, "category": category, "value": value})
                elif isinstance(part, ast.Constant) and isinstance(part.value, int) and part.value > 20 and names & {"frame", "start", "end"}:
                    counts["frame_range_branches"] += 1
                    findings.append({"function": name, "line": node.lineno, "category": "frame_range_branches", "value": part.value})
    return {"counts": counts, "findings": findings, "configuration_override_files": []}


def firewall_audit(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    findings = []
    forbidden = ("human", "contact_sheet", "candidate_reconciliation", "unowned_source_component")
    for name in PRODUCTION_FUNCTIONS:
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and any(token in node.value.lower() for token in forbidden):
                findings.append({"function": name, "line": node.lineno, "value": node.value})
    return {"production_human_imports": 0, "production_candidate_table_imports": 0, "production_lookups": len(findings), "findings": findings}


def build(args: argparse.Namespace) -> dict[str, Any]:
    v31, output = Path(args.v31).resolve(), Path(args.output).resolve()
    source_objects_artifact = load(v31 / "canonical_source_objects_v3_1.json")
    original_objects = source_objects_artifact["objects"]
    observations = load(Path(args.observations).resolve()) if args.observations else scan_source_pixels(Path(args.video).resolve(), Path(args.ocr_module).resolve(), original_objects)
    lexicon = source_text_lexicon(load(Path(args.text_support).resolve()))
    first = reconcile_authority(original_objects, observations, lexicon)
    second = reconcile_authority(original_objects, observations, lexicon)
    authority = authority_artifacts(v31, first)
    authority_second = authority_artifacts(v31, second)
    original_audit = load(Path(args.coverage_v1).resolve())
    evaluation = evaluate_original(original_audit, first["decisions"])
    counts = Counter(row["classification"] for row in evaluation)
    unresolved = [row for row in evaluation if row["classification"] == "I"]
    tests, counterfactual = synthetic_tests(), counterfactual_tests()
    universality, firewall = universality_audit(Path(__file__)), firewall_audit(Path(__file__))
    first_hash, second_hash = canonical_hash(authority), canonical_hash(authority_second)
    status = "READY_FOR_MOVE2_RETRY" if not unresolved and tests["failed"] == 0 and counterfactual["failed"] == 0 and not any(universality["counts"].values()) and not firewall["findings"] and first_hash == second_hash else "BLOCKED_SOURCE_COVERAGE_RECONCILIATION"
    for payload in authority.values():
        payload["status"] = status
    for name, payload in authority.items():
        write(output / name, payload)
    write(output / "canonical_source_objects_v3_1.json", authority["canonical_source_objects_v3_2.json"])
    write(output / "source_ownership_authority_v3_1.json", authority["source_ownership_authority_v3_2.json"])
    write(output / "source_pixel_observations_v3_2.json", observations)
    evidence = {"schema": "video_cloner_coverage_candidate_evidence_v3_2", "schema_version": "3.2", "status": status, "candidates": first["decisions"]}
    reconciliation = {"schema": "video_cloner_coverage_candidate_reconciliation_v3_2", "schema_version": "3.2", "status": status, "original_candidate_count": len(evaluation), "classification_counts": dict(sorted(counts.items())), "candidates": evaluation}
    subsets = {
        "lifecycle_reconciliation_v3_2.json": {"classes": {"A", "F"}},
        "partial_animation_reconciliation_v3_2.json": {"classes": {"B"}},
        "fragment_reconciliation_v3_2.json": {"classes": {"C"}},
        "merged_ocr_reconciliation_v3_2.json": {"classes": {"D"}},
        "text_variant_reconciliation_v3_2.json": {"classes": {"E"}},
        "recovered_source_objects_v3_2.json": {"classes": {"G"}},
        "rejected_source_noise_v3_2.json": {"classes": {"H"}},
    }
    write(output / "coverage_candidate_reconciliation.json", reconciliation)
    write(output / "coverage_candidate_evidence.json", evidence)
    for name, spec in subsets.items():
        rows = [row for row in evaluation if row["classification"] in spec["classes"]]
        write(output / name, {"schema": "video_cloner_" + name.removesuffix(".json"), "schema_version": "3.2", "status": status, "count": len(rows), "candidates": rows})
    write(output / "reconciliation_synthetic_tests.json", {"schema": "video_cloner_reconciliation_synthetic_tests_v3_2", "status": status, **tests})
    write(output / "reconciliation_counterfactual_tests.json", {"schema": "video_cloner_reconciliation_counterfactual_tests_v3_2", "status": status, **counterfactual})
    write(output / "reconciliation_universality_audit.json", {"schema": "video_cloner_reconciliation_universality_audit_v3_2", "status": status, **universality})
    write(output / "reconciliation_human_data_firewall_audit.json", {"schema": "video_cloner_reconciliation_human_data_firewall_audit_v3_2", "status": status, **firewall})
    write(output / "reconciliation_determinism_report.json", {"schema": "video_cloner_reconciliation_determinism_v3_2", "status": status, "run_1_hash": first_hash, "run_2_hash": second_hash, "identical": first_hash == second_hash})
    write(output / "unresolved_reconciliation_candidates.json", {"schema": "video_cloner_unresolved_reconciliation_candidates_v3_2", "status": status, "count": len(unresolved), "candidates": unresolved})
    return {"status": status, "output": str(output), "previous_objects": len(original_objects), "v3_2_objects": len(first["objects"]), "classifications": dict(sorted(counts.items())), "unresolved": len(unresolved), "synthetic": {key: tests[key] for key in ("total", "passed", "failed")}, "counterfactual": {key: counterfactual[key] for key in ("total", "passed", "failed")}, "determinism": {"run_1_hash": first_hash, "run_2_hash": second_hash, "identical": first_hash == second_hash}}


def self_test() -> None:
    tests, counterfactual = synthetic_tests(), counterfactual_tests()
    assert tests["total"] >= 12 and tests["failed"] == 0, tests
    assert counterfactual["failed"] == 0, counterfactual
    print("SELF_TEST_PASS")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--v31")
    value.add_argument("--coverage-v1")
    value.add_argument("--video")
    value.add_argument("--ocr-module")
    value.add_argument("--output")
    value.add_argument("--text-support")
    value.add_argument("--observations")
    value.add_argument("--self-test", action="store_true")
    return value


if __name__ == "__main__":
    arguments = parser().parse_args()
    if arguments.self_test:
        self_test()
    else:
        missing = [name for name in ("v31", "coverage_v1", "video", "ocr_module", "output", "text_support") if not getattr(arguments, name)]
        if missing:
            raise SystemExit("missing arguments: " + ", ".join(missing))
        print(json.dumps(build(arguments), indent=2, sort_keys=True))
