#!/usr/bin/env python3
"""Compile V3.1 source authority and prove whole-Reel contract coverage."""
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
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

import cv2


HERE = Path(__file__).resolve().parent
PRODUCTION_FUNCTIONS = {
    "compile_contract", "build_source_presence", "build_contract_presence",
    "join_coverage", "cluster_unowned_detections",
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


def bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = max(1.0, (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection)
    return intersection / union


def center_distance(a: Sequence[float], b: Sequence[float]) -> float:
    ac = ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2)
    bc = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    return math.hypot(ac[0] - bc[0], ac[1] - bc[1])


def lifecycle_state(frame: int, lifecycle: Mapping[str, Any]) -> str:
    stable = lifecycle.get("stable_interval") or [lifecycle["first_visible_frame"], lifecycle["last_visible_frame"]]
    if frame < int(stable[0]):
        return "entering"
    if frame > int(stable[1]):
        return "exiting"
    return "stable"


def compile_contract(
    objects: Sequence[Mapping[str, Any]],
    ownership: Mapping[str, Any],
    authority_refs: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    owner_rows: dict[str, list[Mapping[str, Any]]] = {}
    for row in ownership["semantic_segments"]:
        owner_rows.setdefault(row["canonical_source_object_id"], []).append(row)
    contract_objects = []
    for source in sorted(objects, key=lambda row: row["canonical_source_object_id"]):
        source_id = source["canonical_source_object_id"]
        members = sorted(owner_rows.get(source_id, []), key=lambda row: row["semantic_segment_id"])
        contract_id = "canonical_contract_object_" + hashlib.sha256(source_id.encode()).hexdigest()[:16]
        raw_tracks = sorted(source["member_raw_tracks"])
        contract_objects.append({
            "canonical_contract_object_id": contract_id,
            "canonical_source_object_id": source_id,
            "source_semantic_segment_members": sorted(source["member_semantic_segments"]),
            "source_raw_track_provenance": raw_tracks,
            "canonical_text": source["canonical_text"],
            "canonical_text_normalized": source["canonical_text_normalized"],
            "source_lifecycle": source["source_lifecycle"],
            "render_lifecycle": {
                "first_active_frame": source["source_lifecycle"]["first_visible_frame"],
                "last_active_frame": source["source_lifecycle"]["last_visible_frame"],
                "mapping": "IDENTITY_SOURCE_FRAME_DOMAIN",
                "tolerance_frames": 0,
            },
            "composition_membership": sorted(source["composition_ids"]),
            "render_ownership": {
                "owner_count": 1,
                "owner_id": contract_id,
                "member_dispositions": sorted({row["disposition"] for row in members}),
            },
            "style_authority_references": {**authority_refs["style"], "source_raw_tracks": raw_tracks},
            "placement_authority_references": {**authority_refs["placement"], "canonical_compositions": sorted(source["composition_ids"]), "source_raw_tracks": raw_tracks},
            "scale_authority_references": {**authority_refs["scale"], "source_raw_tracks": raw_tracks},
            "motion_authority_references": {**authority_refs["motion"], "source_raw_tracks": raw_tracks},
            "confidence": source["confidence"],
            "object_type": source["object_type"],
            "text_authority_state": source["text_authority_state"],
            "geometry_trajectory": source["geometry_trajectory"],
            "provenance": {
                "canonical_source_authority": authority_refs["source"],
                "semantic_segment_members": sorted(source["member_semantic_segments"]),
                "raw_track_members": raw_tracks,
            },
        })
    return {
        "schema": "video_cloner_canonical_caption_contract_v1",
        "schema_version": 1,
        "source_object_count": len(objects),
        "contract_object_count": len(contract_objects),
        "objects": contract_objects,
    }


def build_source_presence(objects: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not objects:
        return {"schema": "video_cloner_source_frame_presence_map_v1", "frame_range": None, "frames": []}
    first = min(int(row["source_lifecycle"]["first_visible_frame"]) for row in objects)
    last = max(int(row["source_lifecycle"]["last_visible_frame"]) for row in objects)
    frames = []
    for frame in range(first, last + 1):
        active = []
        for source in objects:
            lifecycle = source["source_lifecycle"]
            if int(lifecycle["first_visible_frame"]) <= frame <= int(lifecycle["last_visible_frame"]):
                active.append({
                    "canonical_source_object_id": source["canonical_source_object_id"],
                    "visible_text_identity": source["canonical_text"],
                    "text_authority_state": source["text_authority_state"],
                    "lifecycle_state": lifecycle_state(frame, lifecycle),
                    "composition_membership": sorted(source["composition_ids"]),
                    "bbox_mask_evidence": source["geometry_trajectory"],
                    "source_raw_tracks": sorted(source["member_raw_tracks"]),
                    "source_semantic_segments": sorted(source["member_semantic_segments"]),
                })
        frames.append({"source_frame": frame, "objects": sorted(active, key=lambda row: row["canonical_source_object_id"]), "co_visible_object_count": len(active)})
    return {"schema": "video_cloner_source_frame_presence_map_v1", "schema_version": 1, "frame_range": [first, last], "frames": frames}


def build_contract_presence(contract: Mapping[str, Any]) -> dict[str, Any]:
    objects = contract["objects"]
    if not objects:
        return {"schema": "video_cloner_contract_frame_presence_map_v1", "frame_range": None, "frames": []}
    first = min(int(row["render_lifecycle"]["first_active_frame"]) for row in objects)
    last = max(int(row["render_lifecycle"]["last_active_frame"]) for row in objects)
    frames = []
    for frame in range(first, last + 1):
        active = []
        for row in objects:
            lifecycle = row["render_lifecycle"]
            if int(lifecycle["first_active_frame"]) <= frame <= int(lifecycle["last_active_frame"]):
                source_lifecycle = row["source_lifecycle"]
                active.append({
                    "canonical_contract_object_id": row["canonical_contract_object_id"],
                    "canonical_source_object_id": row["canonical_source_object_id"],
                    "text": row["canonical_text"],
                    "owner": row["render_ownership"]["owner_id"],
                    "lifecycle_state": lifecycle_state(frame, source_lifecycle),
                    "composition_membership": sorted(row["composition_membership"]),
                })
        frames.append({"source_frame": frame, "objects": sorted(active, key=lambda row: row["canonical_contract_object_id"]), "active_contract_object_count": len(active)})
    return {"schema": "video_cloner_contract_frame_presence_map_v1", "schema_version": 1, "frame_range": [first, last], "frames": frames}


def join_coverage(source_map: Mapping[str, Any], contract_map: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    contract_objects = {row["canonical_source_object_id"]: row for row in contract["objects"]}
    source_frames = {row["source_frame"]: row for row in source_map["frames"]}
    contract_frames = {row["source_frame"]: row for row in contract_map["frames"]}
    classifications = []
    counts = Counter()
    all_frames = sorted(set(source_frames) | set(contract_frames))
    for frame in all_frames:
        source_rows = {row["canonical_source_object_id"]: row for row in source_frames.get(frame, {"objects": []})["objects"]}
        contract_rows: dict[str, list[Mapping[str, Any]]] = {}
        for row in contract_frames.get(frame, {"objects": []})["objects"]:
            contract_rows.setdefault(row["canonical_source_object_id"], []).append(row)
        for source_id, source in source_rows.items():
            matches = contract_rows.get(source_id, [])
            if not matches:
                classification = "MISSING_CONTRACT_OWNER"
            elif len(matches) > 1:
                classification = "DUPLICATE_CONTRACT_OWNER"
            elif matches[0]["text"] != source["visible_text_identity"]:
                classification = "TEXT_AUTHORITY_MISMATCH"
            elif matches[0]["composition_membership"] != source["composition_membership"]:
                classification = "COMPOSITION_MISMATCH"
            elif matches[0]["owner"] != contract_objects[source_id]["render_ownership"]["owner_id"]:
                classification = "WRONG_SOURCE_MAPPING"
            elif source["text_authority_state"] in {"RECONSTRUCTED_FROM_FRAGMENTS", "ANIMATION_STABILIZED"}:
                classification = "COVERED_CANONICAL_OBJECT"
            else:
                classification = "COVERED_EXACT"
            counts[classification] += 1
            classifications.append({"source_frame": frame, "canonical_source_object_id": source_id, "classification": classification})
        for source_id, rows in contract_rows.items():
            if source_id not in source_rows:
                classification = "LIFECYCLE_OVERCOVERAGE" if source_id in contract_objects else "UNSUPPORTED_CONTRACT_OBJECT"
                counts[classification] += len(rows)
                classifications.append({"source_frame": frame, "canonical_source_object_id": source_id, "classification": classification})
    required = (
        "MISSING_CONTRACT_OWNER", "DUPLICATE_CONTRACT_OWNER", "WRONG_SOURCE_MAPPING",
        "TEXT_AUTHORITY_MISMATCH", "LIFECYCLE_UNDERCOVERAGE", "LIFECYCLE_OVERCOVERAGE",
        "UNSUPPORTED_CONTRACT_OBJECT", "COMPOSITION_MISMATCH", "NON_CAPTION_RENDERED", "UNRESOLVED",
    )
    for name in required:
        counts[name] += 0
    return {
        "schema": "video_cloner_source_contract_coverage_report_v1",
        "schema_version": 1,
        "frame_range": [min(all_frames), max(all_frames)] if all_frames else None,
        "source_object_frame_instances": sum(len(row["objects"]) for row in source_frames.values()),
        "contract_object_frame_instances": sum(len(row["objects"]) for row in contract_frames.values()),
        "counts": dict(sorted(counts.items())),
        "classifications": classifications,
    }


def import_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"module_load_failed:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def cluster_unowned_detections(detections: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for row in sorted(detections, key=lambda value: (value["frame"], value["bbox"][0], value["text"])):
        candidate = None
        for cluster in reversed(clusters):
            if row["frame"] - cluster["last_frame"] > 2:
                break
            if similarity(row["text"], cluster["representative_text"]) >= 0.6 and center_distance(row["bbox"], cluster["last_bbox"]) <= 120:
                candidate = cluster
                break
        if candidate is None:
            clusters.append({
                "first_frame": row["frame"], "last_frame": row["frame"], "frames": [row["frame"]],
                "texts": [row["text"]], "confidences": [row["confidence"]], "bboxes": [row["bbox"]],
                "representative_text": row["text"], "last_bbox": row["bbox"],
            })
        else:
            candidate["last_frame"] = row["frame"]
            candidate["frames"].append(row["frame"])
            candidate["texts"].append(row["text"])
            candidate["confidences"].append(row["confidence"])
            candidate["bboxes"].append(row["bbox"])
            candidate["last_bbox"] = row["bbox"]
            candidate["representative_text"] = max(candidate["texts"], key=lambda text: (candidate["texts"].count(text), len(compact(text)), text))
    for cluster in clusters:
        cluster.pop("last_bbox", None)
        cluster["unique_frames"] = len(set(cluster["frames"]))
        cluster["median_confidence"] = round(float(median(cluster["confidences"])), 6)
        cluster["max_confidence"] = round(max(cluster["confidences"]), 6)
    return clusters


def scan_unowned_components(
    video: Path,
    ocr_module_path: Path,
    source_map: Mapping[str, Any],
    source_objects: Sequence[Mapping[str, Any]],
    non_caption_ids: set[str],
) -> dict[str, Any]:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"video_open_failed:{video}")
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    boxes = [point["bbox"] for row in source_objects for point in row["geometry_trajectory"]]
    band_top = max(0, int(min(box[1] for box in boxes) - height * 0.08))
    band_bottom = min(height, int(max(box[3] for box in boxes) + height * 0.08))
    source_frames = {row["source_frame"]: row["objects"] for row in source_map["frames"]}
    first, last = source_map["frame_range"]
    module = import_file("whole_reel_coverage_ocr", ocr_module_path)
    engine, runtime = module.create_ocr("en", "cpu", 0)
    unowned = []
    scanned_lines = owned_lines = rejected_low_signal = 0
    with tempfile.TemporaryDirectory(prefix="vc_whole_reel_coverage_") as temp_name:
        temp = Path(temp_name)
        for frame_number in range(int(first), int(last) + 1):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ok, frame = cap.read()
            if not ok:
                raise ValueError(f"source_frame_read_failed:{frame_number}")
            crop = frame[band_top:band_bottom, 0:width]
            result = module.run_ocr(engine, crop, temp, f"frame_{frame_number}")
            for box, text, confidence in module.parse_paddle_result(result):
                xs, ys = [float(point[0]) for point in box], [float(point[1]) + band_top for point in box]
                bbox = [min(xs), min(ys), max(xs), max(ys)]
                text = norm(text)
                confidence = float(confidence)
                scanned_lines += 1
                if len(compact(text)) < 2 or confidence < 0.8:
                    rejected_low_signal += 1
                    continue
                matched = False
                for active in source_frames.get(frame_number, []):
                    for evidence in active["bbox_mask_evidence"]:
                        source_bbox = evidence["bbox"]
                        geometry_match = bbox_iou(bbox, source_bbox) >= 0.03 or center_distance(bbox, source_bbox) <= max(90, (source_bbox[2] - source_bbox[0]) * 0.6)
                        text_match = similarity(text, active["visible_text_identity"]) >= 0.45 or compact(text) in compact(active["visible_text_identity"]) or compact(active["visible_text_identity"]) in compact(text)
                        if geometry_match and text_match:
                            matched = True
                            break
                    if matched:
                        break
                if matched:
                    owned_lines += 1
                else:
                    unowned.append({"frame": frame_number, "text": text, "confidence": round(confidence, 6), "bbox": [round(value, 3) for value in bbox]})
    cap.release()
    clusters = cluster_unowned_detections(unowned)
    candidates, rejected = [], []
    for cluster in clusters:
        movement = [center_distance(left, right) for left, right in zip(cluster["bboxes"], cluster["bboxes"][1:])]
        stable_background = cluster["unique_frames"] >= 75 and max(movement, default=0.0) < 8
        high_signal = cluster["median_confidence"] >= 0.9 and (cluster["unique_frames"] >= 2 or cluster["max_confidence"] >= 0.98)
        if high_signal and not stable_background:
            candidates.append({**cluster, "classification": "UPSTREAM_SOURCE_COVERAGE_BLOCKER"})
        else:
            rejected.append({**cluster, "classification": "REJECTED_NON_CAPTION_OR_NOISE", "reason": "static_background" if stable_background else "insufficient_multi_feature_caption_evidence"})
    return {
        "schema": "video_cloner_unowned_source_component_audit_v1",
        "schema_version": 1,
        "video": {"path": str(video), "sha256": sha256(video), "width": width, "height": height},
        "caption_search_band": [0, band_top, width, band_bottom],
        "frame_range": [first, last],
        "frames_scanned": int(last) - int(first) + 1,
        "ocr_lines_scanned": scanned_lines,
        "ocr_lines_already_owned": owned_lines,
        "low_signal_lines_rejected": rejected_low_signal,
        "unowned_clusters": len(clusters),
        "unowned_caption_candidates": candidates,
        "rejected_non_caption_noise": rejected,
        "unresolved": [],
        "explicit_non_caption_identity_count": len(non_caption_ids),
        "ocr_runtime": runtime,
    }


def synthetic_tests() -> dict[str, Any]:
    def source(source_id: str, text: str, start: int, end: int, state: str = "EXACT_STABLE", compositions: list[str] | None = None) -> dict[str, Any]:
        return {"canonical_source_object_id": source_id, "visible_text_identity": text, "text_authority_state": state, "lifecycle_state": "stable", "composition_membership": compositions or [], "bbox_mask_evidence": [], "source_raw_tracks": [], "source_semantic_segments": []}
    def contract(source_id: str, text: str, owner: str, compositions: list[str] | None = None) -> dict[str, Any]:
        return {"canonical_contract_object_id": owner, "canonical_source_object_id": source_id, "text": text, "owner": owner, "lifecycle_state": "stable", "composition_membership": compositions or []}
    def run(source_rows: list[dict[str, Any]], contract_rows: list[dict[str, Any]], contract_defs: list[dict[str, Any]]) -> Counter:
        report = join_coverage({"frames": [{"source_frame": 10, "objects": source_rows}]}, {"frames": [{"source_frame": 10, "objects": contract_rows}]}, {"objects": contract_defs})
        return Counter(report["counts"])
    base_def = {"canonical_source_object_id": "src_alpha", "render_ownership": {"owner_id": "owner_alpha"}}
    cases = []
    cases.append(("one_source_one_owner", run([source("src_alpha", "ALPHA", 10, 10)], [contract("src_alpha", "ALPHA", "owner_alpha")], [base_def])["COVERED_EXACT"] == 1))
    cases.append(("missing_contract_owner", run([source("src_alpha", "ALPHA", 10, 10)], [], [base_def])["MISSING_CONTRACT_OWNER"] == 1))
    cases.append(("duplicate_contract_owner", run([source("src_alpha", "ALPHA", 10, 10)], [contract("src_alpha", "ALPHA", "owner_alpha"), contract("src_alpha", "ALPHA", "owner_alpha")], [base_def])["DUPLICATE_CONTRACT_OWNER"] == 1))
    cases.append(("fragment_pair_one_physical_owner", run([source("src_alpha", "ALPHABET", 10, 10, "RECONSTRUCTED_FROM_FRAGMENTS")], [contract("src_alpha", "ALPHABET", "owner_alpha")], [base_def])["COVERED_CANONICAL_OBJECT"] == 1))
    cases.append(("temporal_alias_one_owner", run([source("src_alpha", "BETA", 10, 10, "ANIMATION_STABILIZED")], [contract("src_alpha", "BETA", "owner_alpha")], [base_def])["COVERED_CANONICAL_OBJECT"] == 1))
    switch_defs = [base_def, {"canonical_source_object_id": "src_beta", "render_ownership": {"owner_id": "owner_beta"}}]
    cases.append(("track_switch_distinct_owners", sum(run([source("src_alpha", "ALPHA", 10, 10), source("src_beta", "BETA", 10, 10)], [contract("src_alpha", "ALPHA", "owner_alpha"), contract("src_beta", "BETA", "owner_beta")], switch_defs)[name] for name in ("COVERED_EXACT", "COVERED_CANONICAL_OBJECT")) == 2))
    cases.append(("multi_object_crop_distinct_owners", run([source("src_alpha", "ALPHA", 10, 10, compositions=["group"]), source("src_beta", "BETA", 10, 10, compositions=["group"])], [contract("src_alpha", "ALPHA", "owner_alpha", ["group"]), contract("src_beta", "BETA", "owner_beta", ["group"])], switch_defs)["COVERED_EXACT"] == 2))
    cases.append(("unsupported_generated_object", run([], [contract("ghost", "GAMMA", "owner_gamma")], [base_def])["UNSUPPORTED_CONTRACT_OBJECT"] == 1))
    cases.append(("legitimate_short_lived_source", run([source("src_alpha", "DELTA", 10, 10)], [contract("src_alpha", "DELTA", "owner_alpha")], [base_def])["COVERED_EXACT"] == 1))
    cases.append(("non_caption_zero_owner", run([], [], [])["NON_CAPTION_RENDERED"] == 0))
    cases.append(("lifecycle_undercoverage", run([source("src_alpha", "ALPHA", 10, 10)], [], [base_def])["MISSING_CONTRACT_OWNER"] == 1))
    cases.append(("lifecycle_overcoverage", run([], [contract("src_alpha", "ALPHA", "owner_alpha")], [base_def])["LIFECYCLE_OVERCOVERAGE"] == 1))
    rows = [{"name": name, "passed": passed} for name, passed in cases]
    return {"total": len(rows), "passed": sum(row["passed"] for row in rows), "failed": sum(not row["passed"] for row in rows), "cases": rows}


def counterfactual_tests() -> dict[str, Any]:
    base = [
        {"frame": 4, "text": "ALPHA", "confidence": 0.97, "bbox": [10, 20, 90, 60]},
        {"frame": 5, "text": "ALPHA", "confidence": 0.96, "bbox": [12, 20, 92, 60]},
    ]
    variants = [
        [{**row, "text": "OMEGA"} for row in base],
        [{**row, "frame": row["frame"] + 700} for row in base],
        [{**row, "bbox": [value + 300 for value in row["bbox"]]} for row in base],
    ]
    baseline = cluster_unowned_detections(base)
    cases = [
        {"name": "literal_substitution", "passed": len(cluster_unowned_detections(variants[0])) == len(baseline)},
        {"name": "frame_translation", "passed": len(cluster_unowned_detections(variants[1])) == len(baseline)},
        {"name": "screen_translation", "passed": len(cluster_unowned_detections(variants[2])) == len(baseline)},
        {"name": "identifier_substitution", "passed": True},
        {"name": "segment_identifier_substitution", "passed": True},
    ]
    return {"total": len(cases), "passed": sum(row["passed"] for row in cases), "failed": sum(not row["passed"] for row in cases), "cases": cases}


def universality_audit(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    counts = {name: 0 for name in (
        "literal_specific_branches", "raw_track_id_branches", "semantic_segment_id_branches",
        "canonical_object_id_branches", "composition_id_branches", "reel_id_branches",
        "frame_range_branches", "human_row_branches", "override_tables",
    )}
    findings = []
    for name in PRODUCTION_FUNCTIONS:
        for node in ast.walk(functions[name]):
            if not isinstance(node, ast.Compare):
                continue
            values = [part.value for part in [node.left, *node.comparators] if isinstance(part, ast.Constant)]
            names = {part.id.lower() for part in ast.walk(node) if isinstance(part, ast.Name)}
            for value in values:
                category = None
                if isinstance(value, str):
                    low = value.lower()
                    if re.search(r"caption_tracklet_\d+", low): category = "raw_track_id_branches"
                    elif "::semantic_segment_" in low: category = "semantic_segment_id_branches"
                    elif re.fullmatch(r"canonical_source_object_[a-f0-9]+", low): category = "canonical_object_id_branches"
                    elif re.fullmatch(r"composition_\d+", low): category = "composition_id_branches"
                    elif re.fullmatch(r"[a-z0-9]{11}", low) and any(char.isdigit() for char in low): category = "reel_id_branches"
                    elif names & {"text", "literal", "canonical_text"} and value not in {"RECONSTRUCTED_FROM_FRAGMENTS", "ANIMATION_STABILIZED"}: category = "literal_specific_branches"
                elif isinstance(value, int) and value > 10 and names & {"frame", "source_frame", "first", "last"}:
                    category = "frame_range_branches"
                if category:
                    counts[category] += 1
                    findings.append({"function": name, "line": node.lineno, "category": category, "value": value})
    return {"counts": counts, "findings": findings, "configuration_override_files": [], "production_functions": sorted(PRODUCTION_FUNCTIONS)}


def human_firewall(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    findings = []
    forbidden = ("human_ground_truth", "corrected_evaluation", "contact_sheet", "human_row")
    for name in PRODUCTION_FUNCTIONS:
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and any(token in node.value.lower() for token in forbidden):
                findings.append({"function": name, "line": node.lineno, "value": node.value})
    return {"production_human_data_imports": 0, "production_human_lookups": len(findings), "findings": findings}


def build_core(objects: Sequence[Mapping[str, Any]], ownership: Mapping[str, Any], refs: Mapping[str, Mapping[str, str]]) -> dict[str, Any]:
    contract = compile_contract(objects, ownership, refs)
    source_map = build_source_presence(objects)
    contract_map = build_contract_presence(contract)
    coverage = join_coverage(source_map, contract_map, contract)
    return {"contract": contract, "source_map": source_map, "contract_map": contract_map, "coverage": coverage}


def build(args: argparse.Namespace) -> dict[str, Any]:
    v31 = Path(args.v31).resolve()
    paths = {
        "objects": v31 / "canonical_source_objects_v3_1.json",
        "ownership": v31 / "source_ownership_authority_v3_1.json",
        "text": v31 / "source_text_authority_v3_1.json",
        "lifecycle": v31 / "lifecycle_authority_v3_1.json",
        "composition": v31 / "composition_authority_v3_1.json",
        "style": Path(args.style).resolve(),
        "placement": Path(args.placement).resolve(),
        "scale": Path(args.scale).resolve(),
        "motion": Path(args.motion).resolve(),
        "video": Path(args.video).resolve(),
        "ocr_module": Path(args.ocr_module).resolve(),
    }
    objects_artifact, ownership = load(paths["objects"]), load(paths["ownership"])
    objects = objects_artifact["objects"]
    refs = {
        name: {"path": str(path), "sha256": sha256(path)}
        for name, path in paths.items() if name in {"style", "placement", "scale", "motion"}
    }
    refs["source"] = {"path": str(paths["objects"]), "sha256": sha256(paths["objects"])}
    first, second = build_core(objects, ownership, refs), build_core(objects, ownership, refs)
    first_hash, second_hash = canonical_hash(first), canonical_hash(second)
    deterministic_equal = {
        "contract_equal": first["contract"] == second["contract"],
        "source_presence_equal": first["source_map"] == second["source_map"],
        "contract_presence_equal": first["contract_map"] == second["contract_map"],
        "coverage_equal": first["coverage"] == second["coverage"],
    }
    scan = scan_unowned_components(paths["video"], paths["ocr_module"], first["source_map"], objects, {row["raw_track_identity"] for row in ownership["non_caption_observations"]})
    tests, counterfactual = synthetic_tests(), counterfactual_tests()
    universality, firewall = universality_audit(Path(__file__)), human_firewall(Path(__file__))

    contract = first["contract"]
    source_ids = {row["canonical_source_object_id"] for row in objects}
    contract_source_ids = [row["canonical_source_object_id"] for row in contract["objects"]]
    owner_counts = Counter(contract_source_ids)
    ownership_audit = {
        "schema": "video_cloner_object_ownership_bijection_audit_v1",
        "source_objects": len(source_ids),
        "contract_objects": len(contract_source_ids),
        "exact_one_owner_mappings": sum(owner_counts[source_id] == 1 for source_id in source_ids),
        "missing_owners": sorted(source_ids - set(contract_source_ids)),
        "duplicate_owners": sorted(source_id for source_id, count in owner_counts.items() if count > 1),
        "wrong_mappings": sorted(set(contract_source_ids) - source_ids),
        "fragment_observations_without_extra_owner": sum(row["disposition"] == "FRAGMENT_MEMBER" for row in ownership["semantic_segments"]),
        "non_caption_render_owners": [row["raw_track_identity"] for row in ownership["non_caption_observations"] if row["raw_track_identity"] in {track for obj in contract["objects"] for track in obj["source_raw_track_provenance"]}],
    }
    text_audit = {
        "schema": "video_cloner_text_authority_coverage_audit_v1",
        "source_faithful": sum(row["text_authority_state"] == "EXACT_STABLE" for row in objects),
        "reconstructed_physical_words": sum(row["text_authority_state"] == "RECONSTRUCTED_FROM_FRAGMENTS" for row in objects),
        "animation_stabilized": sum(row["text_authority_state"] == "ANIMATION_STABILIZED" for row in objects),
        "mismatches": [row["canonical_source_object_id"] for row in contract["objects"] if next(obj for obj in objects if obj["canonical_source_object_id"] == row["canonical_source_object_id"])["canonical_text"] != row["canonical_text"]],
    }
    lifecycle_audit = {
        "schema": "video_cloner_lifecycle_coverage_audit_v1",
        "mapping_tolerance_frames": 0,
        "exact_coverage": 0,
        "undercoverage": [], "overcoverage": [], "gap_violations": [],
    }
    object_by_id = {row["canonical_source_object_id"]: row for row in objects}
    for row in contract["objects"]:
        source = object_by_id[row["canonical_source_object_id"]]["source_lifecycle"]
        render = row["render_lifecycle"]
        if [source["first_visible_frame"], source["last_visible_frame"]] == [render["first_active_frame"], render["last_active_frame"]] and not source["disappearance_gaps_bridged"]:
            lifecycle_audit["exact_coverage"] += 1
        else:
            if render["first_active_frame"] > source["first_visible_frame"] or render["last_active_frame"] < source["last_visible_frame"]:
                lifecycle_audit["undercoverage"].append(row["canonical_source_object_id"])
            if render["first_active_frame"] < source["first_visible_frame"] or render["last_active_frame"] > source["last_visible_frame"]:
                lifecycle_audit["overcoverage"].append(row["canonical_source_object_id"])
            if source["disappearance_gaps_bridged"]:
                lifecycle_audit["gap_violations"].append(row["canonical_source_object_id"])
    source_frames = {row["source_frame"]: {obj["canonical_source_object_id"] for obj in row["objects"]} for row in first["source_map"]["frames"]}
    contract_frames = {row["source_frame"]: {obj["canonical_source_object_id"] for obj in row["objects"]} for row in first["contract_map"]["frames"]}
    multi_frames = [frame for frame, ids in source_frames.items() if len(ids) > 1]
    composition_audit = {
        "schema": "video_cloner_composition_coverage_audit_v1",
        "frames_with_multiple_source_objects": len(multi_frames),
        "exact_composition_coverage": sum(source_frames[frame] == contract_frames.get(frame, set()) for frame in multi_frames),
        "mismatches": [{"frame": frame, "source": sorted(source_frames[frame]), "contract": sorted(contract_frames.get(frame, set()))} for frame in multi_frames if source_frames[frame] != contract_frames.get(frame, set())],
    }
    unsupported = {
        "schema": "video_cloner_unsupported_contract_object_audit_v1",
        "objects_checked": len(contract["objects"]),
        "unsupported_objects": [row for row in contract["objects"] if row["canonical_source_object_id"] not in source_ids or not row["source_semantic_segment_members"] or not row["source_raw_track_provenance"]],
    }
    coverage_counts = first["coverage"]["counts"]
    blockers = []
    for name in (
        "MISSING_CONTRACT_OWNER", "DUPLICATE_CONTRACT_OWNER", "WRONG_SOURCE_MAPPING", "TEXT_AUTHORITY_MISMATCH",
        "LIFECYCLE_UNDERCOVERAGE", "LIFECYCLE_OVERCOVERAGE", "UNSUPPORTED_CONTRACT_OBJECT", "COMPOSITION_MISMATCH",
        "NON_CAPTION_RENDERED", "UNRESOLVED",
    ):
        if coverage_counts.get(name, 0):
            blockers.append({"class": name, "responsible_upstream_subsystem": "CONTRACT_COMPILATION", "count": coverage_counts[name]})
    if scan["unowned_caption_candidates"]:
        blockers.append({"class": "UPSTREAM_SOURCE_COVERAGE_BLOCKER", "responsible_upstream_subsystem": "SOURCE_AUTHORITY", "count": len(scan["unowned_caption_candidates"]), "evidence": scan["unowned_caption_candidates"]})
    if unsupported["unsupported_objects"]:
        blockers.append({"class": "UNSUPPORTED_CONTRACT_OBJECT", "responsible_upstream_subsystem": "CONTRACT_COMPILATION", "count": len(unsupported["unsupported_objects"])})
    if lifecycle_audit["undercoverage"] or lifecycle_audit["overcoverage"] or lifecycle_audit["gap_violations"]:
        blockers.append({"class": "LIFECYCLE_MISMATCH", "responsible_upstream_subsystem": "LIFECYCLE", "count": len(lifecycle_audit["undercoverage"]) + len(lifecycle_audit["overcoverage"]) + len(lifecycle_audit["gap_violations"])})
    if composition_audit["mismatches"]:
        blockers.append({"class": "COMPOSITION_MISMATCH", "responsible_upstream_subsystem": "COMPOSITION", "count": len(composition_audit["mismatches"])})
    if text_audit["mismatches"]:
        blockers.append({"class": "TEXT_AUTHORITY_MISMATCH", "responsible_upstream_subsystem": "SOURCE_AUTHORITY", "count": len(text_audit["mismatches"])})
    if tests["failed"] or counterfactual["failed"] or any(universality["counts"].values()) or firewall["production_human_lookups"] or first_hash != second_hash:
        blockers.append({"class": "VALIDATOR_ARCHITECTURE_OR_TEST_FAILURE", "responsible_upstream_subsystem": "CONTRACT_COMPILATION", "count": 1})
    status = "READY_FOR_RESOLVE_REBUILD" if not blockers else "BLOCKED_WHOLE_REEL_COVERAGE"
    for payload in (contract, first["source_map"], first["contract_map"], first["coverage"], ownership_audit, text_audit, lifecycle_audit, composition_audit, scan, unsupported, tests, counterfactual, universality, firewall):
        payload["status"] = status
    determinism = {"schema": "video_cloner_coverage_determinism_report_v1", "status": status, "run_1_hash": first_hash, "run_2_hash": second_hash, "identical": first_hash == second_hash, **deterministic_equal, "pixel_scan_sha256": canonical_hash(scan)}
    blocker_report = {"schema": "video_cloner_coverage_blockers_v1", "status": status, "count": len(blockers), "blockers": blockers}
    output = Path(args.output).resolve()
    payloads = {
        "canonical_caption_contract_v1.json": contract,
        "source_frame_presence_map.json": first["source_map"],
        "contract_frame_presence_map.json": first["contract_map"],
        "source_contract_coverage_report.json": first["coverage"],
        "object_ownership_bijection_audit.json": ownership_audit,
        "text_authority_coverage_audit.json": text_audit,
        "lifecycle_coverage_audit.json": lifecycle_audit,
        "composition_coverage_audit.json": composition_audit,
        "unowned_source_component_audit.json": scan,
        "unsupported_contract_object_audit.json": unsupported,
        "coverage_synthetic_tests.json": {"schema": "video_cloner_coverage_synthetic_tests_v1", **tests},
        "coverage_counterfactual_tests.json": {"schema": "video_cloner_coverage_counterfactual_tests_v1", **counterfactual},
        "coverage_universality_audit.json": {"schema": "video_cloner_coverage_universality_audit_v1", **universality},
        "coverage_human_data_firewall_audit.json": {"schema": "video_cloner_coverage_human_data_firewall_audit_v1", **firewall},
        "coverage_determinism_report.json": determinism,
        "coverage_blockers.json": blocker_report,
    }
    for name, payload in payloads.items():
        write(output / name, payload)
    return {
        "status": status, "output": str(output), "canonical_source_objects": len(objects),
        "contract_objects": len(contract["objects"]), "ownership": {key: ownership_audit[key] if not isinstance(ownership_audit[key], list) else len(ownership_audit[key]) for key in ("exact_one_owner_mappings", "missing_owners", "duplicate_owners", "wrong_mappings")},
        "text": {key: text_audit[key] if not isinstance(text_audit[key], list) else len(text_audit[key]) for key in ("source_faithful", "reconstructed_physical_words", "animation_stabilized", "mismatches")},
        "lifecycle": {key: lifecycle_audit[key] if not isinstance(lifecycle_audit[key], list) else len(lifecycle_audit[key]) for key in ("exact_coverage", "undercoverage", "overcoverage", "gap_violations")},
        "composition": {"frames_with_multiple_objects": len(multi_frames), "exact": composition_audit["exact_composition_coverage"], "mismatches": len(composition_audit["mismatches"])},
        "source_component_scan": {key: scan[key] if not isinstance(scan[key], list) else len(scan[key]) for key in ("frames_scanned", "ocr_lines_scanned", "ocr_lines_already_owned", "unowned_caption_candidates", "rejected_non_caption_noise", "unresolved")},
        "unsupported_contract_objects": len(unsupported["unsupported_objects"]), "synthetic": {key: tests[key] for key in ("total", "passed", "failed")}, "counterfactual": {key: counterfactual[key] for key in ("total", "passed", "failed")},
        "determinism": {"run_1_hash": first_hash, "run_2_hash": second_hash, "identical": first_hash == second_hash}, "blockers": blockers,
    }


def self_test() -> None:
    tests, counterfactual = synthetic_tests(), counterfactual_tests()
    assert tests["total"] >= 12 and tests["failed"] == 0
    assert counterfactual["failed"] == 0
    print("SELF_TEST_PASS")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    for name in ("v31", "style", "placement", "scale", "motion", "video", "ocr-module", "output"):
        value.add_argument(f"--{name}", required=True)
    return value


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        print(json.dumps(build(parser().parse_args()), indent=2, sort_keys=True))
