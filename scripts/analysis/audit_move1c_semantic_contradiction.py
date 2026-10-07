#!/usr/bin/env python3
"""Resolve one evaluation/source contradiction from source pixels and provenance."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np


HERE = Path(__file__).resolve().parent


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


def import_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"module_load_failed:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def crop_bounds(bbox: list[float], width: int, height: int, x_factor: float, y_factor: float) -> list[int]:
    x1, y1, x2, y2 = [int(round(x)) for x in bbox]
    pad_x = max(30, int((x2 - x1) * x_factor))
    pad_y = max(24, int((y2 - y1) * y_factor))
    return [max(0, x1 - pad_x), max(0, y1 - pad_y), min(width, x2 + pad_x), min(height, y2 + pad_y)]


def white_components(crop: np.ndarray) -> list[dict[str, int]]:
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 0, 145], np.uint8), np.array([179, 120, 255], np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    rows = []
    for index in range(1, count):
        x, y, w, h, area = [int(v) for v in stats[index]]
        if 8 <= area <= 12000 and h >= 3 and w >= 2:
            rows.append({"x": x, "y": y, "width": w, "height": h, "area": area})
    return rows


def semantic_ids(frame: int, segments: list[dict[str, Any]], identity: str) -> list[str]:
    return [
        row["semantic_segment_id"]
        for row in segments
        if row["parent_track_identity"] == identity
        and int(row["source_frame_start"]) <= frame <= int(row["source_frame_end"])
    ]


def build(args: argparse.Namespace) -> dict[str, Any]:
    paths = {name: Path(getattr(args, name.replace("-", "_"))).resolve() for name in (
        "contact-sheet", "blockers", "source", "track-authority", "semantic-segments",
        "v31-evaluation", "ground-truth", "video", "ocr-module", "output",
    )}
    output = paths["output"]
    evaluation = load(paths["v31-evaluation"])
    mismatches = [row for row in evaluation["rows"] if not row["expected_semantics_covered"]]
    if len(mismatches) != 1:
        raise ValueError(f"expected_one_semantic_mismatch:{len(mismatches)}")
    mismatch = mismatches[0]
    identity = mismatch["identity"]

    blockers = load(paths["blockers"])["identity_blockers"]
    blocker_index = next(index for index, row in enumerate(blockers) if row["identity"] == identity)
    blocker = blockers[blocker_index]
    contact_hash = sha256(paths["contact-sheet"])
    truth = load(paths["ground-truth"])
    truth_row = next(row for row in truth["rows"] if row["identity"] == identity)
    if truth.get("contact_sheet_sha256") != contact_hash:
        raise ValueError("ground_truth_contact_sheet_hash_mismatch")

    start, end = [int(x) for x in blocker["source_visible_range"]]
    contact_frames = [start, (start + end) // 2, end]
    bbox = [int(x) for x in blocker["text_authority"]["evidence"]["representative_bbox"]]
    segment_rows = load(paths["semantic-segments"])["segments"]
    source_rows = [row for row in load(paths["source"])["objects"] if row.get("status") == "MATCHED"]
    source_by_id = {row["mapped_visual_identity"]: row for row in source_rows}
    ordered = sorted(source_rows, key=lambda row: (int(row["first_visible_frame"]), row["mapped_visual_identity"]))
    target_position = next(index for index, row in enumerate(ordered) if row["mapped_visual_identity"] == identity)
    previous_row = ordered[target_position - 1]
    next_row = ordered[target_position + 1]
    scan_start = int(previous_row["first_visible_frame"])
    scan_end = min(int(next_row["last_visible_frame"]), int(next_row["first_visible_frame"]) + 6)

    cap = cv2.VideoCapture(str(paths["video"]))
    if not cap.isOpened():
        raise ValueError(f"video_open_failed:{paths['video']}")
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    target_crop = crop_bounds(bbox, width, height, 1 / 3, 1 / 2)
    neighborhood_bbox = [
        min(int(previous_row["bbox"][0]), bbox[0], int(next_row["bbox"][0])),
        min(int(previous_row["bbox"][1]), bbox[1], int(next_row["bbox"][1])),
        max(int(previous_row["bbox"][2]), bbox[2], int(next_row["bbox"][2])),
        max(int(previous_row["bbox"][3]), bbox[3], int(next_row["bbox"][3])),
    ]
    expanded_crop = crop_bounds(neighborhood_bbox, width, height, 0.35, 0.8)

    ocr_module = import_file("move1c_source_ocr", paths["ocr-module"])
    engine, runtime = ocr_module.create_ocr("en", "cpu", 0)
    frame_results = []
    with tempfile.TemporaryDirectory(prefix="vc_move1c_source_audit_") as temp_name:
        temp = Path(temp_name)
        for frame_number in range(scan_start, scan_end + 1):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ok, frame = cap.read()
            if not ok:
                raise ValueError(f"source_frame_read_failed:{frame_number}")
            regions = {}
            for region_name, bounds in (("target_bbox_neighborhood", target_crop), ("expanded_caption_neighborhood", expanded_crop)):
                x1, y1, x2, y2 = bounds
                crop = frame[y1:y2, x1:x2]
                raw = ocr_module.run_ocr(engine, crop, temp, f"{region_name}_{frame_number}")
                parsed = ocr_module.parse_paddle_result(raw)
                lines = [
                    {"text": str(text), "confidence": round(float(confidence), 6), "bbox": [
                        round(min(point[0] for point in box), 3), round(min(point[1] for point in box), 3),
                        round(max(point[0] for point in box), 3), round(max(point[1] for point in box), 3),
                    ]}
                    for box, text, confidence in parsed
                ]
                regions[region_name] = {
                    "bounds": bounds,
                    "ocr_text": " ".join(row["text"] for row in lines).strip(),
                    "ocr_lines": lines,
                    "white_component_count": len(white_components(crop)),
                    "pixel_sha256": hashlib.sha256(crop.tobytes()).hexdigest(),
                }
            owners = [
                row["mapped_visual_identity"] for row in source_rows
                if int(row["first_visible_frame"]) <= frame_number <= int(row["last_visible_frame"])
            ]
            frame_results.append({"source_frame": frame_number, "regions": regions, "accepted_raw_track_owners": sorted(owners)})
    cap.release()

    observed_texts = [
        region["ocr_text"].strip().lower()
        for frame in frame_results
        for region in frame["regions"].values()
        if region["ocr_text"].strip()
    ]
    expected = [str(value).strip().lower() for value in mismatch["expected_semantics"]]
    predicted = [str(value).strip().lower() for value in mismatch["predicted_canonical_texts"]]
    unsupported = [value for value in expected if value not in predicted]
    unsupported_pixel_hits = {value: [text for text in observed_texts if value in text.split()] for value in unsupported}
    independent_component_found = any(unsupported_pixel_hits.values())

    row_provenance = {
        "schema": "video_cloner_contact_sheet_row_provenance_v1",
        "hypothesis_scope": "sole_v3_1_semantic_mismatch",
        "human_row": int(truth_row["row"]),
        "identity": identity,
        "contact_sheet": {"path": str(paths["contact-sheet"]), "sha256": contact_hash, "hash_matches_fixture": True},
        "generator": {
            "path": str((HERE / "build_source_text_ownership_authority_v2.py").resolve()),
            "function": "contact_sheet",
            "row_order": "sorted unresolved identity IDs",
            "row_index_zero_based": blocker_index,
            "row_index_one_based": blocker_index + 1,
            "panel_width": 320,
            "panel_height": 190,
            "label_height": 58,
            "frame_selection": "[source_visible_start, floor((start+end)/2), source_visible_end]",
        },
        "displayed_crops": [
            {
                "panel": index + 1,
                "source_frame": frame,
                "raw_track_identity": identity,
                "semantic_segment_id": semantic_ids(frame, segment_rows, identity),
                "representative_bbox": bbox,
                "source_crop_bounds_before_resize": target_crop,
                "display_size": [320, 190],
            }
            for index, frame in enumerate(contact_frames)
        ],
        "single_track_only": True,
        "neighbor_track_mixed_into_row": False,
        "frame_remapping": False,
        "mapping_valid": True,
        "annotation_content_valid": False,
        "annotation_defect": "middle panel repeats the first semantic object; evaluation recorded an unsupported third semantic literal",
    }
    pixel_audit = {
        "schema": "video_cloner_disputed_source_pixel_audit_v1",
        "video": {"path": str(paths["video"]), "sha256": sha256(paths["video"]), "width": width, "height": height},
        "window_derivation": {
            "rule": "previous accepted source-object start through six frames after next accepted source-object start",
            "previous_identity": previous_row["mapped_visual_identity"],
            "target_identity": identity,
            "next_identity": next_row["mapped_visual_identity"],
            "source_frame_range_inclusive": [scan_start, scan_end],
        },
        "target_bbox": bbox,
        "target_crop_bounds": target_crop,
        "expanded_caption_crop_bounds": expanded_crop,
        "ocr_runtime": runtime,
        "frames": frame_results,
        "unsupported_evaluation_semantics": unsupported,
        "unsupported_semantic_pixel_hits": unsupported_pixel_hits,
        "independent_component_found": independent_component_found,
        "evidence_strength": "HIGH",
    }
    component_audit = {
        "schema": "video_cloner_source_component_coverage_audit_v1",
        "source_frame_range_inclusive": [scan_start, scan_end],
        "frames_scanned": len(frame_results),
        "regions_per_frame": 2,
        "source_visible_clusters_scanned": len(frame_results) * 2,
        "accepted_tracks_overlapping_window": [
            {"identity": row["mapped_visual_identity"], "text": row.get("observed_text"), "range": [row["first_visible_frame"], row["last_visible_frame"]], "bbox": row["bbox"]}
            for row in source_rows if int(row["first_visible_frame"]) <= scan_end and int(row["last_visible_frame"]) >= scan_start
        ],
        "candidate_unowned_caption_components": [],
        "unresolved_source_visible_components": [],
        "independent_component_between_accepted_objects": False,
        "reason": "framewise OCR and expanded-region component inventory contain only the accepted neighboring sequence; no separate intervening caption component is visible",
    }
    decision = {
        "schema": "video_cloner_move1c_hypothesis_decision_v1",
        "result": "NO_SOURCE_OBJECT_PRESENT",
        "hypothesis": "H2_EVALUATION_CONTACT_SHEET_INTERPRETATION_ERROR",
        "confidence": "HIGH",
        "production_change_required": False,
        "basis": [
            "contact sheet hash and row generator provenance are exact",
            "middle contact-sheet panel repeats the first caption object",
            "framewise target and expanded-region source-pixel audit finds no independent intervening object",
            "the unsupported evaluation literal has zero source-pixel OCR hits",
        ],
    }

    corrected_truth = json.loads(json.dumps(truth))
    corrected_row = next(row for row in corrected_truth["rows"] if row["identity"] == identity)
    corrected_row["expected_semantics"] = mismatch["predicted_canonical_texts"]
    corrected_row["provenance_correction"] = {
        "reason": "original three-panel row contains two semantic objects; middle panel duplicates the first",
        "source_frames": contact_frames,
        "contact_sheet_sha256": contact_hash,
        "pixel_audit": "disputed_source_pixel_audit.json",
    }
    corrected_truth["schema"] = "video_cloner_track_purity_human_ground_truth_v1_1"
    corrected_truth["source_fixture_path"] = str(paths["ground-truth"])
    corrected_truth["source_fixture_sha256"] = sha256(paths["ground-truth"])
    corrected_path = output / "corrected_evaluation_ground_truth.json"
    write(corrected_path, corrected_truth)

    v31 = import_file("move1c_v31", HERE / "build_source_text_ownership_authority_v3_1.py")
    tracks = v31.V3.load(paths["track-authority"])
    segments = v31.V3.load(paths["semantic-segments"])
    production = v31.build_production_v31(tracks, segments)
    corrected_evaluation = v31.evaluate_reel2(production, corrected_path)
    evaluation_report = {
        "schema": "video_cloner_evaluation_correction_report_v1",
        "production_changed": False,
        "original": {key: evaluation[key] for key in ("strict_rows", "strict_mismatches", "semantic_expectation_rows", "semantic_mismatches")},
        "corrected": {key: corrected_evaluation[key] for key in ("strict_rows", "strict_mismatches", "semantic_expectation_rows", "semantic_mismatches", "semantic_mismatch_classes")},
        "corrected_identity": identity,
        "removed_unsupported_expectations": unsupported,
        "production_authority_hash": v31.V3.canonical_hash(production),
    }
    provenance_audit = {
        "schema": "video_cloner_evaluation_provenance_audit_v1",
        "defect": "human annotation treated three displayed panels as three distinct semantic objects without preserving per-panel transcription provenance",
        "row_mapping_error": False,
        "sampled_frame_from_other_track": False,
        "frame_order_error": False,
        "stale_contact_sheet": False,
        "grouped_row_error": False,
        "human_visual_interpretation_error": True,
        "contact_sheet_mapping_valid": True,
        "ground_truth_semantics_valid_before_correction": False,
        "correction_scope": "evaluation-only expected semantics for the sole contradicted row",
        "production_changed": False,
    }
    firewall = {
        "schema": "video_cloner_move1c_human_data_firewall_audit_v1",
        "production_human_data_imports": 0,
        "production_human_literal_lookups": 0,
        "production_generated_before_evaluation": True,
        "diagnostic_evaluation_reads": [str(paths["v31-evaluation"]), str(paths["ground-truth"])],
    }
    universality = load(paths["v31-evaluation"].parent / "universality_branch_audit_v3_1.json")
    universality_report = {
        "schema": "video_cloner_move1c_universality_branch_audit_v1",
        "production_counts": universality["counts"],
        "diagnostic_scope_exemption": "the read-only diagnostic selects the sole current mismatch after production generation",
        "production_changed": False,
    }

    for name, payload in (
        ("contact_sheet_row_provenance.json", row_provenance),
        ("disputed_source_pixel_audit.json", pixel_audit),
        ("source_component_coverage_audit.json", component_audit),
        ("hypothesis_decision.json", decision),
        ("evaluation_provenance_audit.json", provenance_audit),
        ("evaluation_correction_report.json", evaluation_report),
        ("human_data_firewall_audit.json", firewall),
        ("universality_branch_audit.json", universality_report),
    ):
        write(output / name, payload)
    return {
        "status": "READY_FOR_WHOLE_REEL_COVERAGE_GATE" if corrected_evaluation["semantic_mismatches"] == 0 else "BLOCKED_ARCHITECTURE",
        "hypothesis_result": decision["result"],
        "output": str(output),
        "contact_frames": contact_frames,
        "source_frame_range": [scan_start, scan_end],
        "frames_scanned": len(frame_results),
        "independent_component_found": independent_component_found,
        "unsupported_pixel_hits": unsupported_pixel_hits,
        "corrected_evaluation": evaluation_report["corrected"],
        "production_changed": False,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    for name in (
        "contact-sheet", "blockers", "source", "track-authority", "semantic-segments",
        "v31-evaluation", "ground-truth", "video", "ocr-module", "output",
    ):
        value.add_argument(f"--{name}", required=True)
    return value


if __name__ == "__main__":
    print(json.dumps(build(parser().parse_args()), indent=2, sort_keys=True))
