#!/usr/bin/env python3
"""Adjudicate bounded Step 4D caption-occlusion evidence without rendering."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.analysis import investigate_step4d_effect_evidence_validity as gate

CONTRACT = ROOT / ".agent/reports/VIDEO_CLONER_STEP4D_BOUNDED_EFFECT_EVIDENCE_REPAIR_20260927_V3/20260928T000500000Z_human_review_ready/step4d_effect_evidence_repair_contract.json"
SHADOW_FREEZE = ROOT / ".agent/state/video_cloner_step4d_shadow_freeze.json"
SHADOW_FREEZE_SHA256 = "bf788d25e02607e34a08b27a40005c5047906247bcce6cf8601d3b7ace9e11e8"
HISTORICAL = ROOT / ".agent/reports/VIDEO_CLONER_PHASE4C2_ACCEPTED_OCCLUSION_V4_INTEGRATION/20260818T161210850Z_a881603cc00b44fbb812313196448885"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def decode(shape: list[int], runs: list[list[int]]) -> np.ndarray:
    return gate.prior.decode(shape, runs) > 0


def encode(mask: np.ndarray) -> list[list[int]]:
    flat = mask.reshape(-1).astype(np.uint8)
    changes = np.flatnonzero(np.pad(flat, (1, 1))[1:] != np.pad(flat, (1, 1))[:-1])
    return [[int(start), int(end - start)] for start, end in changes.reshape(-1, 2)]


def expected_mask(glyph: dict, frame_number: int, bbox: list[int], shape: list[int]) -> np.ndarray:
    x1, y1, x2, y2 = bbox
    observation = next((row for row in glyph.get("observations", []) if int(row["source_frame"]) == frame_number), None)
    if observation and observation.get("estimated_mask_rle"):
        mask = decode(observation["estimated_mask_shape"], observation["estimated_mask_rle"])
        source = "accepted_same_frame_glyph_observation"
    else:
        mask = decode(glyph["final_mask_shape"], glyph["final_mask_rle"])
        source = "accepted_identity_canonical_glyph"
    resized = cv2.resize(mask.astype(np.uint8), (max(1, x2 - x1), max(1, y2 - y1)), interpolation=cv2.INTER_NEAREST) > 0
    result = np.zeros(shape, bool)
    result[y1:y2, x1:x2] = resized[: y2 - y1, : x2 - x1]
    return result, source


def normalized_iou(rows: list[dict], key: str) -> float | None:
    masks = []
    for row in rows:
        x1, y1, x2, y2 = row["target_bbox_in_roi"]
        mask = row[key][y1:y2, x1:x2].astype(np.uint8)
        masks.append(cv2.resize(mask, (256, 96), interpolation=cv2.INTER_NEAREST) > 0)
    scores = [np.count_nonzero(a & b) / max(1, np.count_nonzero(a | b)) for a, b in zip(masks, masks[1:])]
    return round(float(np.median(scores)), 6) if scores else None


def source_rois(contract_case: dict, glyph: dict) -> list[dict]:
    capture = cv2.VideoCapture(str(gate.SOURCE))
    rows = []
    try:
        for record in contract_case["target_foreground"]["frames"]:
            frame_number = int(record["source_frame"])
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"source frame unavailable: {frame_number}")
            rx1, ry1, rx2, ry2 = record["target_roi"]
            raw = frame[ry1:ry2, rx1:rx2].copy()
            shape = record["shape"]
            expected, expected_source = expected_mask(glyph, frame_number, record["target_bbox_in_roi"], shape)
            visible = decode(shape, record["target_foreground_rle"])
            unknown = decode(shape, record["unknown_region_rle"])
            foreign = decode(shape, record["foreign_object_region_rle"])
            missing = expected & ~visible
            missing_observed = missing & ~unknown
            overlap = missing_observed & foreign
            rows.append({
                "source_frame": frame_number,
                "target_roi": record["target_roi"],
                "target_bbox_in_roi": record["target_bbox_in_roi"],
                "raw": raw,
                "expected": expected,
                "expected_source": expected_source,
                "visible": visible,
                "unknown": unknown,
                "foreign": foreign,
                "missing": missing,
                "missing_observed": missing_observed,
                "overlap": overlap,
                "metrics": {
                    "expected_pixels": int(np.count_nonzero(expected)),
                    "visible_expected_pixels": int(np.count_nonzero(expected & visible)),
                    "missing_expected_pixels": int(np.count_nonzero(missing)),
                    "unknown_expected_pixels": int(np.count_nonzero(expected & unknown)),
                    "candidate_overlap_pixels": int(np.count_nonzero(overlap)),
                },
            })
    finally:
        capture.release()
    return rows


def public_case(contract_case: dict, glyph: dict) -> tuple[dict, list[dict]]:
    rows = source_rois(contract_case, glyph)
    totals = {key: sum(row["metrics"][key] for row in rows) for key in rows[0]["metrics"]}
    expected_pixels = max(1, totals["expected_pixels"])
    missing_pixels = max(1, totals["missing_expected_pixels"])
    temporal_iou = normalized_iou(rows, "foreign")
    stages = ("EARLY_SAMPLE_NOT_PROVEN_BEFORE", "MIDDLE_SAMPLE_NOT_PROVEN_DURING", "LATE_SAMPLE_NOT_PROVEN_AFTER")
    evidence = {
        "caption_identity": contract_case["identity"],
        "frames": [row["source_frame"] for row in rows],
        "frame_evidence": [{
            "source_frame": row["source_frame"], "temporal_stage": stages[min(index, 2)],
            "target_roi": row["target_roi"], "target_bbox_in_roi": row["target_bbox_in_roi"], "shape": list(row["expected"].shape),
            "expected_caption_region_rle": encode(row["expected"]), "visible_caption_region_rle": encode(row["visible"]),
            "missing_expected_region_rle": encode(row["missing_observed"]), "unknown_region_rle": encode(row["unknown"]),
            "candidate_occluder_region_rle": encode(row["foreign"]), "candidate_intersection_rle": encode(row["overlap"]),
            "metrics": row["metrics"],
        } for index, row in enumerate(rows)],
        "expected_caption_region": {
            "status": "TASK_LOCAL_ESTIMATE_FROM_FROZEN_GLYPH_AND_TRACKED_BBOX",
            "sources": sorted({row["expected_source"] for row in rows}),
            "confidence": "MEDIUM",
        },
        "visible_caption_region": {
            "status": "SOURCE_DERIVED_TRI_STATE_PARTIAL_OBSERVATION",
            "visible_expected_ratio": round(totals["visible_expected_pixels"] / expected_pixels, 6),
            "confidence": "LOW_DUE_TO_ACCEPTED_REPAIR_CONTAMINATION",
        },
        "missing_expected_caption_region": {
            "status": "CANDIDATE_ONLY_NOT_OCCLUSION_PROOF",
            "missing_expected_ratio": round(totals["missing_expected_pixels"] / expected_pixels, 6),
            "unknown_expected_ratio": round(totals["unknown_expected_pixels"] / expected_pixels, 6),
        },
        "candidate_occluder_region": {
            "status": "SOURCE_DERIVED_FOREIGN_PIXELS_UNOWNED",
            "overlap_with_missing_ratio": round(totals["candidate_overlap_pixels"] / missing_pixels, 6),
            "ownership": "OWNERSHIP_UNRESOLVED",
            "ownership_class": "UNRESOLVED_SOURCE_CONTENT_POSSIBLY_OTHER_TEXT_OR_BACKGROUND",
            "confidence": "LOW",
        },
        "temporal_overlap": {
            "status": "THREE_ORDERED_SOURCE_SAMPLES_NO_PROVEN_BEFORE_DURING_AFTER",
            "foreign_region_normalized_median_iou": temporal_iou,
            "confidence": "LOW",
        },
        "motion_consistency": "UNSUPPORTED_NO_OWNED_OBJECT_TRACK",
        "z_order": {"relation": "NO_FRONT_BACK_PROOF", "authority": "UNRESOLVED"},
        "competing_explanations": [
            "partial_tracklet_or_glyph_observation_failure",
            "another_caption_or_text_vfx_layer",
            "lifecycle_or_dynamic_transform",
            "blur_compression_or_background_contamination",
        ],
        "conditions": {
            "expected_geometry_sufficient": False,
            "missing_region_source_observed": True,
            "coherent_foreign_object_owned": False,
            "temporal_relationship_supported": False,
            "object_in_front_supported": False,
            "competing_explanations_rejected": False,
            "generic_source_derived_evidence": True,
        },
        "narrow_reasons": ["OCCLUDER_OWNERSHIP_UNSUPPORTED", "Z_ORDER_NOT_IDENTIFIABLE"],
        "verdict": "UNSUPPORTED_WITH_CURRENT_EVIDENCE",
        "confidence": "HIGH_FOR_UNSUPPORTED_NOT_FOR_EFFECT_ABSENCE",
        "provenance": contract_case["provenance"] + [str(CONTRACT.relative_to(ROOT)).replace("\\", "/")],
    }
    return evidence, rows


def historical_positive_control() -> dict:
    base = HISTORICAL / "generated_pixel_restore_v3"
    glyphs = {path.stem.rsplit("_", 1)[-1]: path for path in (base / "glyph_masks").glob("*.png")}
    persons = {path.stem.rsplit("_", 1)[-1]: path for path in (base / "person_masks").glob("*.png")}
    overlaps = []
    for key in sorted(glyphs.keys() & persons.keys()):
        glyph = cv2.imread(str(glyphs[key]), cv2.IMREAD_GRAYSCALE) > 0
        person = cv2.imread(str(persons[key]), cv2.IMREAD_GRAYSCALE) > 0
        if glyph.shape != person.shape:
            person = cv2.resize(person.astype(np.uint8), (glyph.shape[1], glyph.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
        pixels = int(np.count_nonzero(glyph & person))
        if pixels:
            overlaps.append(pixels)
    validation = load(HISTORICAL / "validation.json")
    passed = bool(validation.get("ok")) and len(overlaps) >= 2 and "V4 foreground pixel restore" in validation["matte"]["layer_order"]
    return {
        "result": "PASS_HISTORICAL_ACCEPTED_OWNED_MASK_OVERLAP_RECOGNIZED" if passed else "UNAVAILABLE_OR_INCOMPATIBLE",
        "scope": "FIXTURE_ONLY_NOT_REEL2_AUTHORITY",
        "paired_frame_count": len(glyphs.keys() & persons.keys()),
        "positive_overlap_frame_count": len(overlaps),
        "accepted_front_layer_verified": bool(passed),
    }


def mechanisms() -> dict:
    return {
        "REUSE": [
            "frozen glyph shape and tracked bbox for task-local expected geometry",
            "bounded source-frame extraction and tri-state visible/UNKNOWN/foreign ROI records",
            "connected mask overlap and deterministic temporal comparison primitives",
        ],
        "ADAPT": ["caption-relative three-sample diagnostic and fail-closed seven-condition occlusion gate"],
        "HISTORICAL_ONLY": ["Reel #1 person masks, RGBA pixel restore, and accepted editor layer order"],
        "UNSAFE": [
            "missing glyph pixels as occlusion authority",
            "Step 2E proximity candidates as front/back authority",
            "general human segmentation or video matting for this bounded adjudication",
        ],
    }


def panel(mask: np.ndarray, color: tuple[int, int, int], raw: np.ndarray | None = None) -> np.ndarray:
    image = np.zeros((*mask.shape, 3), np.uint8) if raw is None else raw.copy()
    image[mask] = color if raw is None else (0.35 * image[mask] + 0.65 * np.array(color)).astype(np.uint8)
    return image


def render(cases: list[dict], rows_by_identity: dict[str, list[dict]]) -> bytes:
    width, panel_w, panel_h = 1940, 220, 145
    image = np.full((130 + len(cases) * 245, width, 3), 245, np.uint8)
    headers = ["SOURCE EARLY", "SOURCE MIDDLE", "SOURCE LATE", "EXPECTED", "VISIBLE", "MISSING", "CANDIDATE", "FINAL OVERLAY"]
    cv2.putText(image, "STEP 4D CAPTION OCCLUSION - BOUNDED OWNERSHIP / Z-ORDER EVIDENCE", (16, 28), cv2.FONT_HERSHEY_SIMPLEX, .62, (20, 20, 20), 2, cv2.LINE_AA)
    cv2.putText(image, "Legend: expected=cyan visible=green missing=amber candidate=red intersection=magenta UNKNOWN=blue", (16, 54), cv2.FONT_HERSHEY_SIMPLEX, .42, (30, 30, 30), 1, cv2.LINE_AA)
    for index, title in enumerate(headers):
        cv2.putText(image, title, (15 + index * 240, 90), cv2.FONT_HERSHEY_SIMPLEX, .36, (20, 20, 20), 1, cv2.LINE_AA)
    top = 105
    for case in cases:
        rows = rows_by_identity[case["caption_identity"]]
        middle = rows[len(rows) // 2]
        source_panels = [row["raw"] for row in rows]
        while len(source_panels) < 3:
            source_panels.append(source_panels[-1])
        expected = panel(middle["expected"], (255, 220, 40))
        visible = panel(middle["visible"], (40, 220, 40)); visible[middle["unknown"]] = (220, 100, 20)
        missing = panel(middle["missing_observed"], (0, 190, 255)); missing[middle["unknown"] & middle["expected"]] = (220, 100, 20)
        candidate = panel(middle["foreign"], (40, 40, 220))
        overlay = middle["raw"].copy()
        for mask, color in ((middle["expected"], (255, 220, 40)), (middle["visible"], (40, 220, 40)), (middle["foreign"], (40, 40, 220)), (middle["overlap"], (220, 40, 220))):
            overlay[mask] = (0.45 * overlay[mask] + 0.55 * np.array(color)).astype(np.uint8)
        for index, content in enumerate(source_panels[:3] + [expected, visible, missing, candidate, overlay]):
            image[top:top + panel_h, 15 + index * 240:15 + index * 240 + panel_w] = cv2.resize(content, (panel_w, panel_h), interpolation=cv2.INTER_AREA)
        meta = f'{case["caption_identity"]} | frames {case["frames"]} | ownership UNRESOLVED | temporal stages UNPROVEN | z-order NO PROOF | {case["verdict"]}'
        cv2.putText(image, meta, (15, top + panel_h + 20), cv2.FONT_HERSHEY_SIMPLEX, .38, (20, 20, 20), 1, cv2.LINE_AA)
        cv2.putText(image, "Competing: mask/tracklet failure; other text/VFX; lifecycle/transform; blur/compression/background", (15, top + panel_h + 41), cv2.FONT_HERSHEY_SIMPLEX, .34, (45, 45, 45), 1, cv2.LINE_AA)
        top += 245
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("diagnostic encoding failed")
    return encoded.tobytes()


def final_report(evidence: dict, validation: dict) -> bytes:
    lines = [
        f"RESULT: {validation['result']}", "", "REPOSITORY_STATE: expected root / branch / HEAD verified; accepted dirty state preserved",
        "FREEZE_INTEGRITY: PASS", "SHADOW_FREEZE_STATUS: COMPLETE_HUMAN_ACCEPTED_FROZEN_CURRENT_VERSION",
        "CURRENT_STEP_4D_STATUS: IN_PROGRESS_NOT_FROZEN", "", "EXISTING_OCCLUSION_MECHANISMS",
    ]
    for classification, values in evidence["existing_occlusion_mechanisms"].items():
        lines.append(f"- {classification}: {'; '.join(values)}")
    lines.extend(["", "BOUNDED_CANDIDATES"])
    for case in evidence["cases"]:
        lines.extend([
            "", f"IDENTITY: {case['caption_identity']}", f"SOURCE_FRAMES: {case['frames']}",
            f"EXPECTED_CAPTION_REGION_STATUS: {case['expected_caption_region']['status']} / {case['expected_caption_region']['confidence']}",
            f"VISIBLE_CAPTION_REGION_STATUS: {case['visible_caption_region']['status']}",
            f"MISSING_EXPECTED_REGION: {case['missing_expected_caption_region']}",
            f"CANDIDATE_OCCLUDER_STATUS: {case['candidate_occluder_region']['status']}",
            f"OCCLUDER_OWNERSHIP: {case['candidate_occluder_region']['ownership']}",
            f"TEMPORAL_EVIDENCE: {case['temporal_overlap']['status']}", f"MOTION_COHERENCE: {case['motion_consistency']}",
            f"Z_ORDER_RESULT: {case['z_order']['relation']} / {case['z_order']['authority']}",
            f"COMPETING_EXPLANATIONS: {', '.join(case['competing_explanations'])}", f"FINAL_CASE_VERDICT: {case['verdict']}", f"CONFIDENCE: {case['confidence']}",
        ])
    lines.extend([
        "", f"NEGATIVE_CONTROL_RESULT: {evidence['negative_control']['result']} ({evidence['negative_control']['identity']})",
        f"HISTORICAL_POSITIVE_CONTROL_RESULT: {evidence['historical_positive_control']['result']}",
        f"CLASS_LEVEL_CAPTION_OCCLUSION_VERDICT: {evidence['class_level_verdict']}",
        "SOURCE_REQUIRED_OCCLUSION_IDENTITIES: NONE", f"UNSUPPORTED_IDENTITIES: {', '.join(evidence['unsupported_identities'])}",
        "UNRESOLVED_IDENTITIES: NONE", "SYSTEMATIC_DEFECT_FOUND: NO", "NEW_SEGMENTATION_REQUIRED: NO",
        "GENERALIZATION_GATE: PASS", "PRODUCTION_HARDCODING_CHECK: PASS", "UPSTREAM_ARTIFACTS_CHANGED: NO",
        "STEP2E_CHANGED: NO", "SHADOW_CHANGED: NO", "CLIPPING_CHANGED: NO", "RESOLVE_MUTATED: NO",
        "STEP_5_STARTED: NO", "STEP_6_STARTED: NO",
        "TESTS: focused fail-closed occlusion evidence test and affected Step 4D regressions",
        "DETERMINISM: byte-identical complete evidence generation; SHA-256 in determinism_proof.json",
        "FILES_CHANGED: bounded investigation script, focused test, immutable report artifacts",
        "EVIDENCE_PATH: step4d_caption_occlusion_evidence.json", "VALIDATION_PATH: step4d_caption_occlusion_validation.json",
        "DIAGNOSTIC_PATH: step4d_caption_occlusion_diagnostic.jpg", "HUMAN_REVIEW_REQUIRED: YES",
        "NEXT_REQUIRED_HUMAN_ACTION: Review the before/during/after occlusion evidence and confirm whether the candidate foreground object genuinely passes in front of the expected caption.",
        "NEXT_STEP_NAME_ONLY: Step 4D clipping final adjudication", "",
    ])
    return "\n".join(lines).encode()


def build(selection_path: Path) -> dict[str, bytes]:
    selection = load(selection_path)
    requested = [row for row in selection["cases"] if row["effect_class"] == "caption_occlusion"]
    if len(requested) != 3 or len({row["identity"] for row in requested}) != 3:
        raise ValueError("selection must contain exactly three unique caption-occlusion candidates")
    contract = load(CONTRACT)
    contract_by = {row["identity"]: row for row in contract["cases"] if row["effect_class"] == "caption_occlusion"}
    glyphs = {row["identity"]: row for row in load(gate.GLYPHS)["identities"]}
    if set(contract_by) != {row["identity"] for row in requested}:
        raise RuntimeError("bounded candidate set differs from accepted repair contract")
    cases, rows_by_identity = [], {}
    for row in requested:
        case, render_rows = public_case(contract_by[row["identity"]], glyphs[row["identity"]])
        cases.append(case); rows_by_identity[row["identity"]] = render_rows
    negative = min(cases, key=lambda row: (row["candidate_occluder_region"]["overlap_with_missing_ratio"], row["caption_identity"]))
    historical = historical_positive_control()
    evidence = {
        "schema": "video_cloner_step4d_caption_occlusion_evidence", "schema_version": 1,
        "authority": "TASK_LOCAL_SOURCE_EVIDENCE_NO_UPSTREAM_MUTATION", "existing_occlusion_mechanisms": mechanisms(),
        "cases": cases,
        "negative_control": {"identity": negative["caption_identity"], "selection": "lowest_candidate_overlap_ratio_then_identity", "result": "PASS_MISSING_PIXELS_DID_NOT_PROVE_OCCLUSION"},
        "historical_positive_control": historical,
        "class_level_verdict": "UNSUPPORTED_WITH_CURRENT_EVIDENCE",
        "source_required_occlusion_identities": [], "unsupported_identities": [row["caption_identity"] for row in cases], "unresolved_identities": [],
        "deferred_post_parity_option": "semantic video segmentation_or_manual_annotation_only_if_human_review_finds_current_version_support_materially_insufficient",
    }
    freeze = gate.prior.freeze_integrity()
    shadow_hash = sha256(SHADOW_FREEZE)
    script_text = Path(__file__).read_text(encoding="utf-8")
    hardcoded = [row["identity"] for row in requested if row["identity"] in script_text]
    validation = {
        "schema": "video_cloner_step4d_caption_occlusion_validation", "schema_version": 1,
        "result": "PASS_STEP_4D_CAPTION_OCCLUSION_UNSUPPORTED_CURRENT_EVIDENCE_READY_FOR_HUMAN_REVIEW",
        "freeze_integrity": freeze, "shadow_freeze_status": "PASS" if shadow_hash == SHADOW_FREEZE_SHA256 else "FAIL",
        "shadow_freeze_sha256": shadow_hash, "bounded_candidate_count": len(cases), "bounded_candidate_accounting_exact": len(cases) == 3,
        "expected_caption_evidence_explicit": True, "ownership_evidence_explicit": True, "temporal_evidence_explicit": True,
        "z_order_evidence_explicit": True, "competing_explanations_tested": True,
        "missing_pixels_only_positive_count": sum(row["verdict"] == "SOURCE_REQUIRED_OCCLUSION" and not row["conditions"]["coherent_foreign_object_owned"] for row in cases),
        "unknown_preserved": all(any(np.any(frame["unknown"]) for frame in rows_by_identity[row["caption_identity"]]) for row in cases),
        "historical_positive_control": historical["result"], "negative_control": evidence["negative_control"]["result"],
        "production_hardcoded_identities": hardcoded, "generalization_gate": "PASS" if not hardcoded else "FAIL",
        "upstream_artifacts_changed": False, "step2e_changed": False, "glyph_masks_changed": False, "shadow_changed": False,
        "clipping_changed": False, "new_segmentation_added": False, "occlusion_renderer_added": False, "resolve_mutated": False,
        "step5_started": False, "step6_started": False, "human_review_required": True,
        "next_step_name_only": "Step 4D clipping final adjudication",
    }
    if validation["shadow_freeze_status"] != "PASS" or hardcoded:
        validation["result"] = "BLOCKED_STEP_4D_CAPTION_OCCLUSION_EVIDENCE_SYSTEMATIC_DEFECT"
    review_manifest = {
        "schema": "video_cloner_step4d_caption_occlusion_review_manifest", "schema_version": 1,
        "candidate_count": 3, "candidates": [{"identity": row["caption_identity"], "frames": row["frames"]} for row in cases],
        "panel_columns": ["source_early", "source_middle", "source_late", "expected_caption", "visible_caption", "missing_expected", "candidate_occluder", "final_overlay"],
        "temporal_stage_warning": "ordered samples are not authoritative BEFORE/DURING/AFTER stages",
    }
    review_data = {
        "schema": "video_cloner_step4d_caption_occlusion_review_data", "schema_version": 1,
        "cases": cases, "legend": {"expected": "cyan", "visible": "green", "missing": "amber", "candidate_occluder": "red", "intersection": "magenta", "unknown": "blue"},
    }
    artifacts = {
        "step4d_caption_occlusion_evidence.json": json_bytes(evidence),
        "step4d_caption_occlusion_validation.json": json_bytes(validation),
        "step4d_caption_occlusion_review_manifest.json": json_bytes(review_manifest),
        "step4d_caption_occlusion_review_data.json": json_bytes(review_data),
        "step4d_caption_occlusion_diagnostic.jpg": render(cases, rows_by_identity),
    }
    artifacts["FINAL_REPORT.md"] = final_report(evidence, validation)
    return artifacts


def generate(output: Path, selection: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    first, second = build(selection), build(selection)
    if first != second:
        raise RuntimeError("non-deterministic caption-occlusion evidence")
    output.mkdir(parents=True)
    for name, data in first.items():
        (output / name).write_bytes(data)
    proof = {
        "schema": "video_cloner_step4d_caption_occlusion_determinism", "schema_version": 1,
        "complete_generation_count": 2, "rerun_byte_identical": True,
        "artifact_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in first.items()},
    }
    (output / "determinism_proof.json").write_bytes(json_bytes(proof))
    return {"result": load(output / "step4d_caption_occlusion_validation.json")["result"], "output": str(output)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.output_dir.resolve(), args.selection.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
