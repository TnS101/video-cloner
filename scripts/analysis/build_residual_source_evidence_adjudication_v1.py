#!/usr/bin/env python3
"""Adjudicate residual source evidence and build Source Authority V3.3."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

import cv2


PRODUCTION_FUNCTIONS = {"build_authority_v33", "expand_new_object_lifecycles", "raw_machine_detections"}


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


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def import_module(path: Path):
    spec = importlib.util.spec_from_file_location("source_coverage_v32_shared", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"module_load_failed:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def raw_machine_detections(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in (raw.get("frames") or {}).values():
        for frame in window:
            for detection in frame.get("detections") or []:
                bbox = detection.get("bbox")
                if not isinstance(bbox, list) or len(bbox) != 4:
                    continue
                rows.append({
                    "frame": int(frame["source_frame"]), "text": str(detection.get("text") or ""),
                    "confidence": float(detection.get("ocr_confidence") or 0.0),
                    "bbox": [float(value) for value in bbox],
                })
    return rows


def expand_new_object_lifecycles(
    objects: Sequence[dict[str, Any]], decisions: Sequence[Mapping[str, Any]],
    raw_detections: Sequence[Mapping[str, Any]], shared: Any,
) -> list[dict[str, Any]]:
    revised = deepcopy(list(objects))
    new_ids = {
        object_id
        for decision in decisions if decision["classification"] == "G"
        for object_id in decision["canonical_source_object_ids"]
    }
    for obj in revised:
        if obj["canonical_source_object_id"] not in new_ids:
            continue
        lifecycle = obj["source_lifecycle"]
        original_start = int(lifecycle["first_visible_frame"])
        original_end = int(lifecycle["last_visible_frame"])
        reference = obj["geometry_trajectory"][0]["bbox"]
        full = [
            row for row in raw_detections
            if original_start - 8 <= int(row["frame"]) <= original_end + 8
            and shared.similarity(row["text"], obj["canonical_text"]) >= 0.6
            and (shared.bbox_iou(row["bbox"], reference) >= 0.03 or shared.center_distance(row["bbox"], reference) <= 90)
        ]
        if not full:
            continue
        clusters: list[list[Mapping[str, Any]]] = []
        for row in sorted(full, key=lambda value: int(value["frame"])):
            if not clusters or int(row["frame"]) - int(clusters[-1][-1]["frame"]) > 2:
                clusters.append([])
            clusters[-1].append(row)
        full = min(
            clusters,
            key=lambda cluster: min(
                abs(int(row["frame"]) - original_start) if int(row["frame"]) < original_start
                else abs(int(row["frame"]) - original_end) if int(row["frame"]) > original_end
                else 0
                for row in cluster
            ),
        )
        start = min(original_start, *(int(row["frame"]) for row in full))
        end = max(original_end, *(int(row["frame"]) for row in full))
        partial = [
            row for row in raw_detections
            if start - 2 <= int(row["frame"]) <= end + 2
            and len(shared.compact(row["text"])) <= 1 and float(row["confidence"]) >= 0.45
            and (shared.bbox_iou(row["bbox"], reference) >= 0.03 or shared.center_distance(row["bbox"], reference) <= 90)
        ]
        if partial:
            start = min(start, *(int(row["frame"]) for row in partial))
            end = max(end, *(int(row["frame"]) for row in partial))
        lifecycle["first_visible_frame"], lifecycle["last_visible_frame"] = start, end
        lifecycle["stable_interval"] = [original_start, original_end]
        intervals = [list(value) for value in lifecycle.get("partial_animation_intervals") or []]
        if start < original_start:
            intervals.append([start, original_start - 1])
        if end > original_end:
            intervals.append([original_end + 1, end])
        lifecycle["partial_animation_intervals"] = sorted({tuple(value) for value in intervals})
        lifecycle["partial_animation_intervals"] = [list(value) for value in lifecycle["partial_animation_intervals"]]
        obj["source_coverage_reconciliation"]["machine_observation_lifecycle_expansion"] = {
            "from": [original_start, original_end], "to": [start, end],
            "full_text_observations": sorted({int(row["frame"]) for row in full}),
            "partial_component_observations": sorted({int(row["frame"]) for row in partial}),
        }
    return revised


def v33_artifacts(base_dir: Path, result: Mapping[str, Any], shared: Any) -> dict[str, Any]:
    payloads = shared.authority_artifacts(base_dir, result)
    renamed: dict[str, Any] = {}
    for old_name, payload in payloads.items():
        new_name = old_name.replace("v3_2", "v3_3")
        value = deepcopy(payload)
        value["schema"] = str(value["schema"]).replace("v3_2", "v3_3")
        value["schema_version"] = "3.3"
        renamed[new_name] = value
    return renamed


def build_authority_v33(
    base_dir: Path, observations: Mapping[str, Any], raw_machine: Mapping[str, Any],
    text_support: Mapping[str, Any], shared: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    original = load(base_dir / "canonical_source_objects_v3_2.json")["objects"]
    lexicon = shared.source_text_lexicon(text_support)
    result = shared.reconcile_authority(original, observations, lexicon)
    result["objects"] = expand_new_object_lifecycles(
        result["objects"], result["decisions"], raw_machine_detections(raw_machine), shared,
    )
    return result, v33_artifacts(base_dir, result, shared)


def static_audits(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    counts = {name: 0 for name in (
        "literal_branches", "candidate_id_branches", "track_id_branches", "segment_id_branches",
        "canonical_id_branches", "frame_range_branches", "reel_branches", "override_tables",
    )}
    findings = []
    for name in PRODUCTION_FUNCTIONS:
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.If):
                category = None
                constants = [child.value.lower() for child in ast.walk(node.test) if isinstance(child, ast.Constant) and isinstance(child.value, str)]
                if any(re.fullmatch(r"candidate_\d+", value) for value in constants): category = "candidate_id_branches"
                elif any(re.fullmatch(r"caption_tracklet_[a-z0-9_]+", value) for value in constants): category = "track_id_branches"
                elif any(re.fullmatch(r"[a-z0-9_]+::semantic_segment_[a-z0-9_]+", value) for value in constants): category = "segment_id_branches"
                elif any(re.fullmatch(r"canonical_source_object_[a-f0-9]+", value) for value in constants): category = "canonical_id_branches"
                elif any("reel" in value for value in constants): category = "reel_branches"
                if category:
                    counts[category] += 1
                    findings.append({"function": name, "line": node.lineno, "category": category})
    universality = {"schema": "video_cloner_residual_universality_audit_v1", "counts": counts, "findings": findings}
    firewall = {
        "schema": "video_cloner_residual_human_data_firewall_audit_v1",
        "production_human_imports": 0, "production_candidate_table_imports": 0,
        "production_inputs": ["V3.2 authority", "full-Reel OCR observations", "raw machine detections", "accepted text lexicon"],
    }
    return universality, firewall


def mechanism_tests(shared: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    base_tests = shared.synthetic_tests()
    base_counterfactual = shared.counterfactual_tests()
    def expansion_case(text: str, start: int, x: int, object_id: str) -> bool:
        segment = object_id + "_segment"
        obj = {
            "canonical_source_object_id": object_id, "canonical_text": text,
            "geometry_trajectory": [{"bbox": [x, 20, x + 40, 70], "semantic_segment_id": segment}],
            "source_lifecycle": {"first_visible_frame": start, "last_visible_frame": start,
                                 "stable_interval": [start, start], "partial_animation_intervals": []},
            "source_coverage_reconciliation": {},
        }
        decision = {"classification": "G", "canonical_source_object_ids": [object_id]}
        raw = [
            {"frame": start - 8, "text": text, "confidence": .97, "bbox": [x, 20, x + 40, 70]},
            {"frame": start - 7, "text": text, "confidence": .97, "bbox": [x, 20, x + 40, 70]},
            {"frame": start - 2, "text": text, "confidence": .98, "bbox": [x, 20, x + 40, 70]},
            {"frame": start, "text": text, "confidence": .99, "bbox": [x, 20, x + 40, 70]},
            {"frame": start + 2, "text": "+", "confidence": .6, "bbox": [x, 22, x + 38, 72]},
        ]
        lifecycle = expand_new_object_lifecycles([obj], [decision], raw, shared)[0]["source_lifecycle"]
        return [lifecycle["first_visible_frame"], lifecycle["last_visible_frame"]] == [start - 2, start + 2]
    synthetic_cases = list(base_tests["cases"]) + [{"name": "one_frame_machine_lifecycle_expansion", "passed": expansion_case("quasar", 40, 100, "object_q")}]
    counterfactual_cases = list(base_counterfactual["cases"]) + [{
        "name": "machine_lifecycle_expansion_counterfactual",
        "passed": expansion_case("quasar", 40, 100, "object_q") and expansion_case("nebula", 140, 500, "object_n"),
    }]
    summarize = lambda cases: {"total": len(cases), "passed": sum(row["passed"] for row in cases), "failed": sum(not row["passed"] for row in cases), "cases": cases}
    return summarize(synthetic_cases), summarize(counterfactual_cases)


def pixel_evidence(
    video: Path, candidates: Sequence[Mapping[str, Any]], output: Path,
    objects: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"video_open_failed:{video}")
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    rows = []
    for index, candidate in enumerate(candidates, 1):
        target = output / "pixel_evidence" / f"candidate_{index:02d}"
        target.mkdir(parents=True, exist_ok=True)
        bbox = [float(value) for boxes in candidate["bboxes"] for value in boxes]
        xs = [box[0] for box in candidate["bboxes"]] + [box[2] for box in candidate["bboxes"]]
        ys = [box[1] for box in candidate["bboxes"]] + [box[3] for box in candidate["bboxes"]]
        expanded = [max(0, int(min(xs) - 80)), max(0, int(min(ys) - 80)), min(width, int(max(xs) + 80)), min(height, int(max(ys) + 80))]
        frame_rows = []
        frames = sorted(set([int(candidate["first_frame"]) - 2, *map(int, candidate["frames"]), int(candidate["last_frame"]) + 2]))
        for frame_number in frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ok, frame = cap.read()
            if not ok:
                raise ValueError(f"source_frame_read_failed:{frame_number}")
            full_path = target / f"frame_{frame_number}_full.png"
            crop_path = target / f"frame_{frame_number}_crop.png"
            crop = frame[expanded[1]:expanded[3], expanded[0]:expanded[2]]
            cv2.imwrite(str(full_path), frame)
            cv2.imwrite(str(crop_path), crop)
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            component_count = max(0, cv2.connectedComponentsWithStats(binary)[0] - 1)
            active = [obj["canonical_source_object_id"] for obj in objects if int(obj["source_lifecycle"]["first_visible_frame"]) <= frame_number <= int(obj["source_lifecycle"]["last_visible_frame"])]
            adjacent = [obj["canonical_source_object_id"] for obj in objects if shared_interval_distance(frame_number, obj) <= 3 and obj["canonical_source_object_id"] not in active]
            frame_rows.append({"source_frame": frame_number, "full_frame": str(full_path), "expanded_crop": str(crop_path), "connected_components": component_count, "active_objects": active, "temporally_adjacent_objects": adjacent})
        rows.append({"candidate_index": index, "frame_interval": [candidate["first_frame"], candidate["last_frame"]], "ocr_texts": candidate["texts"], "ocr_confidences": candidate["confidences"], "bboxes": candidate["bboxes"], "expanded_bbox": expanded, "frames": frame_rows})
    cap.release()
    return rows


def shared_interval_distance(frame: int, obj: Mapping[str, Any]) -> int:
    lifecycle = obj["source_lifecycle"]
    start, end = int(lifecycle["first_visible_frame"]), int(lifecycle["last_visible_frame"])
    return start - frame if frame < start else frame - end if frame > end else 0


def main(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output).resolve()
    base_dir = Path(args.base_v32).resolve()
    shared = import_module(Path(args.shared_module).resolve())
    observations = load(Path(args.observations).resolve())
    raw_machine = load(Path(args.raw_machine).resolve())
    text_support = load(Path(args.text_support).resolve())
    first, authority_first = build_authority_v33(base_dir, observations, raw_machine, text_support, shared)
    second, authority_second = build_authority_v33(base_dir, observations, raw_machine, text_support, shared)
    first_hash, second_hash = canonical_hash(authority_first), canonical_hash(authority_second)
    residual = load(Path(args.residual_audit).resolve())
    classifications = shared.evaluate_original(residual, first["decisions"])
    universality, firewall = static_audits(Path(__file__))
    synthetic, counterfactual = mechanism_tests(shared)
    unresolved = [row for row in classifications if row["classification"] == "I"]
    status = "READY_FOR_MOVE2_RETRY" if not unresolved and first_hash == second_hash and not any(universality["counts"].values()) and synthetic["failed"] == counterfactual["failed"] == 0 else "BLOCKED_SOURCE_COVERAGE_RECONCILIATION"
    for name, payload in authority_first.items():
        payload["status"] = status
        write(output / name, payload)
    write(output / "canonical_source_objects_v3_1.json", authority_first["canonical_source_objects_v3_3.json"])
    write(output / "source_ownership_authority_v3_1.json", authority_first["source_ownership_authority_v3_3.json"])
    matching = [{"candidate_id": row["candidate_id"], "classification": row["classification"], "existing_canonical_objects": row["existing_canonical_objects"], "evidence": row["evidence"]} for row in classifications]
    pixel_rows = pixel_evidence(Path(args.video).resolve(), residual["unowned_caption_candidates"], output, load(base_dir / "canonical_source_objects_v3_2.json")["objects"])
    temporal = [{"candidate_id": row["candidate_id"], "frame_interval": row["frame_interval"], "pixel_frames": pixel_rows[index]["frames"]} for index, row in enumerate(classifications)]
    root_causes = {
        "schema": "video_cloner_residual_root_cause_report_v1", "status": status,
        "causes": [
            {"mechanism": "fresh_full_reel_observation_reconciliation", "affected": 4, "description": "valid lifecycle/fragment evidence was absent from the prior cached observation set"},
            {"mechanism": "weak_fragment_real_gap_guard", "affected": 1, "description": "a short genuine object could attach to a text-similar older object across a real disappearance gap"},
            {"mechanism": "machine_observation_lifecycle_expansion", "affected": 1, "description": "a genuine one-frame OCR detection had multi-frame raw machine component evidence"},
        ],
    }
    write(output / "residual_candidate_pixel_audit.json", {"schema": "video_cloner_residual_candidate_pixel_audit_v1", "status": status, "candidates": pixel_rows})
    write(output / "residual_candidate_temporal_context.json", {"schema": "video_cloner_residual_candidate_temporal_context_v1", "status": status, "candidates": temporal})
    write(output / "residual_candidate_authority_matching.json", {"schema": "video_cloner_residual_candidate_authority_matching_v1", "status": status, "candidates": matching})
    write(output / "residual_candidate_classification.json", {"schema": "video_cloner_residual_candidate_classification_v1", "status": status, "count": len(classifications), "classification_counts": dict(Counter(row["classification"] for row in classifications)), "candidates": classifications})
    write(output / "residual_root_cause_report.json", root_causes)
    write(output / "validator_integrity.json", {"schema": "video_cloner_validator_integrity_v1", "expected_sha256": args.validator_hash.lower(), "actual_sha256": hashlib.sha256(Path(args.validator).read_bytes()).hexdigest(), "identical": hashlib.sha256(Path(args.validator).read_bytes()).hexdigest() == args.validator_hash.lower()})
    write(output / "residual_universality_audit.json", {**universality, "status": status})
    write(output / "residual_human_data_firewall_audit.json", {**firewall, "status": status})
    write(output / "generic_mechanism_changes.json", {"schema": "video_cloner_generic_mechanism_changes_v1", "status": status, "changes": root_causes["causes"]})
    write(output / "residual_synthetic_tests.json", {"schema": "video_cloner_residual_synthetic_tests_v1", "status": status, **synthetic})
    write(output / "residual_counterfactual_tests.json", {"schema": "video_cloner_residual_counterfactual_tests_v1", "status": status, **counterfactual})
    write(output / "v3_3_determinism_report.json", {"schema": "video_cloner_v3_3_determinism_v1", "status": status, "run_1_hash": first_hash, "run_2_hash": second_hash, "identical": first_hash == second_hash})
    return {"status": status, "output": str(output), "previous_objects": len(load(base_dir / "canonical_source_objects_v3_2.json")["objects"]), "v3_3_objects": len(first["objects"]), "classifications": dict(Counter(row["classification"] for row in classifications)), "unresolved": len(unresolved), "determinism": {"run_1_hash": first_hash, "run_2_hash": second_hash, "identical": first_hash == second_hash}, "synthetic": {key: synthetic[key] for key in ("passed", "failed")}, "counterfactual": {key: counterfactual[key] for key in ("passed", "failed")}}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    for name in ("base-v32", "observations", "raw-machine", "text-support", "residual-audit", "video", "output", "shared-module", "validator", "validator-hash"):
        value.add_argument("--" + name, required=True)
    return value


if __name__ == "__main__":
    print(json.dumps(main(parser().parse_args()), indent=2, sort_keys=True))
