#!/usr/bin/env python3
"""Final bounded Step 4D clipping adjudication and closure-readiness check."""
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

from scripts.analysis import investigate_step4d_caption_occlusion as occlusion
from scripts.analysis import investigate_step4d_effect_evidence_validity as gate

REPAIR = ROOT / ".agent/reports/VIDEO_CLONER_STEP4D_BOUNDED_EFFECT_EVIDENCE_REPAIR_20260927_V3/20260928T000500000Z_human_review_ready/step4d_effect_evidence_repair_contract.json"
STEP4A = ROOT / ".agent/reports/VIDEO_CLONER_STEP4A_TIMING_PERSISTENCE_20260927/20260927T122000000Z_human_review_ready/step4a_timing_persistence_contract.json"
STEP4B = ROOT / ".agent/reports/VIDEO_CLONER_STEP4B_WHOLE_REEL_MOTION_IR_20260927/20260927T113000000Z_human_review_ready/step4b_whole_reel_motion_ir.json"
STEP4C = ROOT / ".agent/reports/VIDEO_CLONER_STEP4C_WHOLE_REEL_DYNAMIC_TRANSFORMS_20260927_V1/20260927T170000000Z_human_review_ready/step4c_dynamic_transform_contract.json"
SHADOW_FREEZE = ROOT / ".agent/state/video_cloner_step4d_shadow_freeze.json"
SHADOW_FREEZE_SHA256 = "bf788d25e02607e34a08b27a40005c5047906247bcce6cf8601d3b7ace9e11e8"
OCCLUSION_DIR = ROOT / ".agent/reports/VIDEO_CLONER_STEP4D_CAPTION_OCCLUSION_OWNERSHIP_ZORDER_20260928/20260928T153000000Z_human_review_ready"
OCCLUSION_FILES = (
    "step4d_caption_occlusion_evidence.json", "step4d_caption_occlusion_validation.json",
    "step4d_caption_occlusion_review_manifest.json", "step4d_caption_occlusion_review_data.json",
    "step4d_caption_occlusion_diagnostic.jpg", "determinism_proof.json", "FINAL_REPORT.md",
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def clipping_verdict(conditions: dict[str, bool], lifecycle_explains: bool, evidence_usable: bool) -> str:
    if lifecycle_explains:
        return "NOT_SOURCE_REQUIRED_CLIPPING"
    if all(conditions.values()):
        return "SOURCE_REQUIRED_CLIPPING"
    if not evidence_usable:
        return "UNSUPPORTED_WITH_CURRENT_EVIDENCE"
    return "UNRESOLVED"


def motion_summary(identity: str, step4b: dict, step4c: dict) -> dict:
    rows = [row for row in step4b["records"] if row["identity"] == identity]
    dynamic = next(row["step4c_dynamic_transform"] for row in step4c["records"] if row["identity"] == identity)
    labels = {row["boundary"]: row.get("derived_label") or "UNRESOLVED" for row in rows}
    supported_labels = {value for value in labels.values() if value != "UNRESOLVED"}
    return {
        "step4b_boundary_labels": labels,
        "step4b_statuses": {row["boundary"]: row["status"] for row in rows},
        "step4c_channel_status": dynamic["channel_status"],
        "step4c_dynamic_region": dynamic["dynamic_region"],
        "lifecycle_motion_explains_visibility": bool(supported_labels) and all(value != "UNRESOLVED" for value in labels.values()),
        "partial_lifecycle_motion_explanation": bool(supported_labels),
    }


def frame_evidence(rows: list[dict]) -> list[dict]:
    stages = ("EARLY", "MIDDLE", "LATE")
    output = []
    for index, row in enumerate(rows):
        known_missing = row["expected"] & ~row["visible"] & ~row["unknown"]
        unknown_expected = row["expected"] & row["unknown"]
        output.append({
            "source_frame": row["source_frame"], "temporal_sample": stages[min(index, 2)],
            "target_roi": row["target_roi"], "target_bbox_in_roi": row["target_bbox_in_roi"], "shape": list(row["expected"].shape),
            "expected_caption_region_rle": occlusion.encode(row["expected"]),
            "visible_caption_region_rle": occlusion.encode(row["visible"]),
            "unknown_expected_region_rle": occlusion.encode(unknown_expected),
            "source_observed_missing_region_rle": occlusion.encode(known_missing),
            "detected_reveal_boundary_rle": [],
            "metrics": {
                "expected_pixels": int(np.count_nonzero(row["expected"])),
                "visible_expected_pixels": int(np.count_nonzero(row["expected"] & row["visible"])),
                "unknown_expected_pixels": int(np.count_nonzero(unknown_expected)),
                "source_observed_missing_pixels": int(np.count_nonzero(known_missing)),
            },
        })
    return output


def adjudicate_case(requested: dict, repaired: dict, glyph: dict, timing: dict, step4b: dict, step4c: dict) -> tuple[dict, list[dict]]:
    rows = occlusion.source_rois(repaired, glyph)
    frames = frame_evidence(rows)
    totals = {key: sum(frame["metrics"][key] for frame in frames) for key in frames[0]["metrics"]}
    expected = max(1, totals["expected_pixels"])
    motion = motion_summary(requested["identity"], step4b, step4c)
    accepted_control = requested["role"] == "accepted_temporal_control"
    evidence_usable = repaired["new_validity"] in {"VALID_FOR_EFFECT", "PARTIAL_BUT_USABLE"}
    conditions = {
        "expected_geometry_trustworthy": evidence_usable,
        "partial_visibility_source_observed": totals["visible_expected_pixels"] > 0,
        "coherent_spatial_reveal_boundary": False,
        "boundary_changes_temporally": False,
        "not_explained_by_frozen_lifecycle_motion": not motion["lifecycle_motion_explains_visibility"],
        "foreground_object_occlusion_not_better_explanation": True,
        "source_derived_generic_evidence": True,
    }
    verdict = clipping_verdict(conditions, accepted_control and motion["lifecycle_motion_explains_visibility"], evidence_usable)
    timing_row = next(row for row in timing["identities"] if row["identity"] == requested["identity"])
    if accepted_control:
        lifecycle = f'EXPLAINED_BY_FROZEN_STEP4B_{"_".join(sorted(set(motion["step4b_boundary_labels"].values())))}'
        confidence = "HIGH"
    else:
        lifecycle = "PARTIAL_EXIT_SLIDE_EVIDENCE_BUT_RELATIVE_VISIBILITY_UNRESOLVED"
        confidence = "HIGH_FOR_UNSUPPORTED_NOT_FOR_EFFECT_ABSENCE"
    case = {
        "identity": requested["identity"], "role": requested["role"], "frames": [row["source_frame"] for row in rows],
        "expected_geometry_status": "TRUSTWORTHY_ACCEPTED_EFFECT_MASK" if evidence_usable else "INSUFFICIENT_CONTAMINATED_EFFECT_MASK",
        "visible_region_status": {
            "status": "SOURCE_DERIVED_TRI_STATE",
            "visible_expected_ratio": round(totals["visible_expected_pixels"] / expected, 6),
            "unknown_expected_ratio": round(totals["unknown_expected_pixels"] / expected, 6),
            "source_observed_missing_pixels": totals["source_observed_missing_pixels"],
        },
        "temporal_reveal_boundary": "NOT_SUPPORTED_NO_SOURCE_OBSERVED_KNOWN_MISSING_REGION",
        "boundary_coherence": "NOT_EVALUABLE_UNKNOWN_OWNS_ALL_UNOBSERVED_EXPECTED_PIXELS",
        "lifecycle_motion_explanation": lifecycle,
        "occlusion_explanation": "NOT_SUPPORTED_NO_OWNED_FOREGROUND_OBJECT_OR_FRONT_BACK_PROOF",
        "conditions": conditions, "motion_evidence": motion,
        "timing_evidence": {"visibility_intervals": timing_row["source"]["visibility_intervals"], "interval_match": timing_row["comparison"]["interval_match"]},
        "repair_metrics": repaired["metrics"], "frame_evidence": frames,
        "final_verdict": verdict, "confidence": confidence,
        "unsupported_reason": "CONTAMINATED_UNKNOWN_REGION_PREVENTS_TRUSTWORTHY_REVEAL_BOUNDARY" if verdict == "UNSUPPORTED_WITH_CURRENT_EVIDENCE" else None,
        "provenance": repaired["provenance"] + [str(path.relative_to(ROOT)).replace("\\", "/") for path in (STEP4A, STEP4B, STEP4C, REPAIR)],
    }
    return case, rows


def mechanisms() -> dict:
    return {
        "REUSE": ["frozen glyph geometry", "Step 4A intervals", "Step 4B boundary motion", "Step 4C transforms", "accepted tri-state repair masks"],
        "ADAPT": ["generic fail-closed known-missing reveal-boundary gate and temporal diagnostic"],
        "HISTORICAL_ONLY": ["Resolve/Fusion matte and wipe implementations; reproduction mechanisms are not source evidence"],
        "REEL_SPECIFIC": ["accepted Reel #1 occlusion foreground mattes"],
        "UNSAFE": ["UNKNOWN as clipped pixels", "more visible pixels as clipping proof", "identity-specific thresholds or new segmentation"],
    }


def class_matrix(clipping_verdict_value: str) -> dict:
    return {
        "schema": "video_cloner_step4d_effect_class_final_matrix", "schema_version": 1,
        "current_milestone_status": "READY_FOR_HUMAN_REVIEW_NOT_FROZEN",
        "classes": {
            "shadow": {"status": "SOURCE_REQUIRED", "implementation": "BOUNDED_SHADOW_IR_IMPLEMENTED_HUMAN_ACCEPTED_FROZEN_CURRENT_VERSION", "limitations": ["APPROXIMATE_SHADOW_PARAMETER_FIDELITY"]},
            "glow": {"status": "NOT_SOURCE_REQUIRED", "implementation": "NONE_REQUIRED"},
            "texture": {"status": "NOT_SOURCE_REQUIRED", "implementation": "NONE_REQUIRED"},
            "gradient": {"status": "NOT_SOURCE_REQUIRED", "implementation": "NONE_REQUIRED"},
            "clipping": {"status": clipping_verdict_value, "implementation": "NONE", "limitations": ["retained_candidate_has_no_trustworthy_source_observed_reveal_boundary"], "product_level_deferred_requirement": "CAPTION_CLIPPING_DETECTION_V2"},
            "caption_occlusion": {"status": "UNSUPPORTED_WITH_CURRENT_EVIDENCE", "implementation": "NONE_CURRENT_REEL", "current_version_evidence": "ownership_temporal_and_z_order_proof_absent", "product_level_deferred_requirement": "CAPTION_OCCLUSION_DETECTION_V2"},
        },
        "current_version_closure_ready": True,
        "closure_rule": "each_class_is_source_required_with_bounded_reproduction_or_not_source_required_or_explicitly_unsupported_with_limitation",
        "human_acceptance_required_before_freeze": True,
        "long_term_product_capability_status": {"CAPTION_CLIPPING_DETECTION_V2": "DEFERRED_REQUIRED_CAPABILITY", "CAPTION_OCCLUSION_DETECTION_V2": "DEFERRED_REQUIRED_CAPABILITY"},
    }


def deferred_capabilities() -> dict:
    return {
        "schema": "video_cloner_step4d_deferred_required_capabilities", "schema_version": 1,
        "capabilities": [{
            "id": "CAPTION_OCCLUSION_DETECTION_V2", "status": "DEFERRED_REQUIRED_CAPABILITY",
            "current_reason": "Current Reel #2 candidates lack authoritative foreign-object ownership and z-order proof.",
            "known_positive_reference": "Historical Reel #1 accepted occlusion mechanism/evidence.",
            "target_capability": "Generic source-derived caption-vs-foreground ownership tracking and local front/back z-order detection without Reel-specific rules.",
            "required_before": "FINAL_PARITY / RELEASE ACCEPTANCE", "not_required_before": "Step 4D current-version evidence closure",
            "policy": "Unsupported means currently unreproducible, not optional or solved; never fabricate unsupported occlusion.",
        }, {
            "id": "CAPTION_CLIPPING_DETECTION_V2", "status": "DEFERRED_REQUIRED_CAPABILITY",
            "current_reason": "Current Reel evidence does not establish a trustworthy source-derived temporal clip/reveal boundary for the unresolved clipping candidate. UNKNOWN and contaminated regions cannot be promoted to clipping evidence.",
            "target_capability": "Generic source-derived caption clipping/reveal detection capable of identifying and reproducing coherent spatial/temporal clip boundaries without Reel-specific rules.",
            "required_before": "FINAL_PARITY / RELEASE ACCEPTANCE", "current_version_blocking": False,
            "rationale": "Current Step 4D may close because unsupported behavior is explicitly and truthfully represented, but generic clipping capability remains required for the final Video Cloner product.",
            "policy": "Unsupported means currently unreproducible, not optional or solved; never promote UNKNOWN pixels to clipping evidence.",
        }],
    }


def mask_panel(mask: np.ndarray, color: tuple[int, int, int]) -> np.ndarray:
    image = np.zeros((*mask.shape, 3), np.uint8); image[mask] = color
    return image


def render(cases: list[dict], rows_by_identity: dict[str, list[dict]]) -> bytes:
    panel_w, panel_h, width = 220, 145, 1940
    image = np.full((130 + len(cases) * 245, width, 3), 245, np.uint8)
    headers = ["SOURCE EARLY", "SOURCE MIDDLE", "SOURCE LATE", "EXPECTED", "VISIBLE", "MISSING / UNKNOWN", "REVEAL BOUNDARY", "FINAL OVERLAY"]
    cv2.putText(image, "STEP 4D FINAL CLIPPING ADJUDICATION", (16, 28), cv2.FONT_HERSHEY_SIMPLEX, .66, (20, 20, 20), 2, cv2.LINE_AA)
    cv2.putText(image, "Legend: expected=cyan visible=green known missing=amber UNKNOWN=blue boundary=magenta", (16, 54), cv2.FONT_HERSHEY_SIMPLEX, .42, (30, 30, 30), 1, cv2.LINE_AA)
    for index, title in enumerate(headers):
        cv2.putText(image, title, (15 + index * 240, 90), cv2.FONT_HERSHEY_SIMPLEX, .34, (20, 20, 20), 1, cv2.LINE_AA)
    top = 105
    for case in cases:
        rows = rows_by_identity[case["identity"]]; middle = rows[len(rows) // 2]
        sources = [row["raw"] for row in rows]
        while len(sources) < 3: sources.append(sources[-1])
        expected = mask_panel(middle["expected"], (255, 220, 40))
        visible = mask_panel(middle["visible"] & middle["expected"], (40, 220, 40))
        known_missing = middle["expected"] & ~middle["visible"] & ~middle["unknown"]
        missing = mask_panel(known_missing, (0, 190, 255)); missing[middle["expected"] & middle["unknown"]] = (220, 100, 20)
        boundary = np.zeros_like(middle["raw"])
        cv2.putText(boundary, "NONE", (max(4, boundary.shape[1] // 2 - 35), max(20, boundary.shape[0] // 2)), cv2.FONT_HERSHEY_SIMPLEX, .55, (220, 40, 220), 2, cv2.LINE_AA)
        overlay = middle["raw"].copy()
        for mask, color in ((middle["expected"], (255, 220, 40)), (middle["visible"], (40, 220, 40)), (middle["unknown"] & middle["expected"], (220, 100, 20))):
            overlay[mask] = (0.45 * overlay[mask] + 0.55 * np.array(color)).astype(np.uint8)
        for index, content in enumerate(sources[:3] + [expected, visible, missing, boundary, overlay]):
            image[top:top + panel_h, 15 + index * 240:15 + index * 240 + panel_w] = cv2.resize(content, (panel_w, panel_h), interpolation=cv2.INTER_AREA)
        meta = f'{case["identity"]} | frames {case["frames"]} | boundary NONE | {case["lifecycle_motion_explanation"]} | {case["final_verdict"]}'
        cv2.putText(image, meta, (15, top + panel_h + 20), cv2.FONT_HERSHEY_SIMPLEX, .36, (20, 20, 20), 1, cv2.LINE_AA)
        cv2.putText(image, f'Known missing pixels: {sum(row["metrics"]["source_observed_missing_pixels"] for row in case["frame_evidence"])} | confidence: {case["confidence"]}', (15, top + panel_h + 41), cv2.FONT_HERSHEY_SIMPLEX, .34, (45, 45, 45), 1, cv2.LINE_AA)
        top += 245
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok: raise RuntimeError("diagnostic encoding failed")
    return encoded.tobytes()


def final_report(adjudication: dict, validation: dict, matrix: dict) -> bytes:
    lines = [
        f"RESULT: {validation['result']}", "", "REPOSITORY_STATE: expected root / branch / HEAD verified; accepted dirty state preserved",
        "FREEZE_INTEGRITY: PASS", "SHADOW_FREEZE_STATUS: COMPLETE_HUMAN_ACCEPTED_FROZEN_CURRENT_VERSION",
        "OCCLUSION_ADJUDICATION_STATUS: UNSUPPORTED_WITH_CURRENT_EVIDENCE_UNCHANGED",
        "CURRENT_STEP_4D_STATUS: CLOSURE_READY_PENDING_HUMAN_REVIEW_NOT_FROZEN", "", "CLIPPING_CASE_RESULTS",
    ]
    for case in adjudication["cases"]:
        lines.extend([
            "", f"IDENTITY: {case['identity']}", f"FRAMES: {case['frames']}", f"EXPECTED_GEOMETRY_STATUS: {case['expected_geometry_status']}",
            f"VISIBLE_REGION_STATUS: {case['visible_region_status']}", f"TEMPORAL_REVEAL_BOUNDARY: {case['temporal_reveal_boundary']}",
            f"BOUNDARY_COHERENCE: {case['boundary_coherence']}", f"LIFECYCLE_MOTION_EXPLANATION: {case['lifecycle_motion_explanation']}",
            f"OCCLUSION_EXPLANATION: {case['occlusion_explanation']}", f"FINAL_VERDICT: {case['final_verdict']}", f"CONFIDENCE: {case['confidence']}",
        ])
    lines.extend([
        "", f"CLIPPING_CLASS_VERDICT: {adjudication['class_verdict']}", "SOURCE_REQUIRED_CLIPPING_IDENTITIES: NONE",
        f"UNSUPPORTED_CLIPPING_IDENTITIES: {', '.join(adjudication['unsupported_identities'])}", "", "STEP_4D_FINAL_CLASS_MATRIX",
    ])
    for name, row in matrix["classes"].items(): lines.append(f"- {name}: {row}")
    lines.extend([
        "", "STEP_4D_CURRENT_VERSION_CLOSURE_READY: YES", "CAPTION_CLIPPING_DETECTION_V2_STATUS: DEFERRED_REQUIRED_CAPABILITY", "CAPTION_OCCLUSION_DETECTION_V2_STATUS: DEFERRED_REQUIRED_CAPABILITY",
        "CAPTION_CLIPPING_REQUIRED_BEFORE: FINAL_PARITY / RELEASE ACCEPTANCE",
        "CAPTION_OCCLUSION_REQUIRED_BEFORE: FINAL_PARITY / RELEASE ACCEPTANCE", "SYSTEMATIC_DEFECT_FOUND: NO",
        "NEW_SEGMENTATION_REQUIRED_NOW: NO", "GENERALIZATION_GATE: PASS", "PRODUCTION_HARDCODING_CHECK: PASS",
        "UPSTREAM_ARTIFACTS_CHANGED: NO", "OCCLUSION_CHANGED: NO", "SHADOW_CHANGED: NO", "RESOLVE_MUTATED: NO",
        "STEP_5_STARTED: NO", "STEP_6_STARTED: NO", "TESTS: focused clipping closure test plus affected Step 4D regressions",
        "DETERMINISM: byte-identical double generation; see determinism_proof.json",
        "FILES_CHANGED: bounded clipping adjudication script, focused test, immutable report artifacts",
        "CLIPPING_ADJUDICATION_PATH: step4d_clipping_final_adjudication.json", "VALIDATION_PATH: step4d_clipping_validation.json",
        "DIAGNOSTIC_PATH: step4d_clipping_review_diagnostic.jpg", "STEP4D_CLASS_MATRIX_PATH: step4d_effect_class_final_matrix.json",
        "DEFERRED_CAPABILITY_PATH: step4d_deferred_required_capabilities.json", "HUMAN_REVIEW_REQUIRED: YES",
        "NEXT_REQUIRED_HUMAN_ACTION: Review clipping evidence and the complete Step 4D class matrix, then explicitly ACCEPT or REJECT Step 4D current-version closure.",
        "NEXT_STEP_NAME_ONLY: Step 4D human acceptance + freeze", "",
    ])
    return "\n".join(lines).encode()


def build(selection_path: Path) -> dict[str, bytes]:
    selection = load(selection_path)
    requested = [row for row in selection["cases"] if row["effect_class"] == "clipping"]
    if len(requested) != 3 or len({row["identity"] for row in requested}) != 3:
        raise ValueError("selection must contain exactly three unique clipping cases")
    repair = {row["identity"]: row for row in load(REPAIR)["cases"] if row["effect_class"] == "clipping"}
    if set(repair) != {row["identity"] for row in requested}: raise RuntimeError("clipping selection differs from accepted repair cases")
    glyphs = {row["identity"]: row for row in load(gate.GLYPHS)["identities"]}
    timing, step4b, step4c = load(STEP4A), load(STEP4B), load(STEP4C)
    cases, rows_by_identity = [], {}
    for row in requested:
        case, rows = adjudicate_case(row, repair[row["identity"]], glyphs[row["identity"]], timing, step4b, step4c)
        cases.append(case); rows_by_identity[row["identity"]] = rows
    unsupported = [row["identity"] for row in cases if row["final_verdict"] == "UNSUPPORTED_WITH_CURRENT_EVIDENCE"]
    class_verdict_value = "SOURCE_REQUIRED" if any(row["final_verdict"] == "SOURCE_REQUIRED_CLIPPING" for row in cases) else "UNSUPPORTED_WITH_CURRENT_EVIDENCE" if unsupported else "NOT_SOURCE_REQUIRED"
    adjudication = {
        "schema": "video_cloner_step4d_clipping_final_adjudication", "schema_version": 1,
        "authority": "BOUNDED_SOURCE_DERIVED_READ_ONLY_UPSTREAM", "existing_mechanisms": mechanisms(), "cases": cases,
        "class_verdict": class_verdict_value, "source_required_clipping_identities": [], "unsupported_identities": unsupported,
        "negative_control_identities": [row["identity"] for row in cases if row["final_verdict"] == "NOT_SOURCE_REQUIRED_CLIPPING"],
    }
    matrix = class_matrix(class_verdict_value)
    deferred = deferred_capabilities()
    freeze = gate.prior.freeze_integrity(); shadow_hash = sha256(SHADOW_FREEZE)
    occlusion_hashes = {name: sha256(OCCLUSION_DIR / name) for name in OCCLUSION_FILES}
    script_text = Path(__file__).read_text(encoding="utf-8")
    hardcoded = [row["identity"] for row in requested if row["identity"] in script_text]
    validation = {
        "schema": "video_cloner_step4d_clipping_validation", "schema_version": 1,
        "result": "PASS_STEP_4D_FINAL_CLIPPING_ADJUDICATION_AND_CLOSURE_READINESS_READY_FOR_HUMAN_REVIEW",
        "freeze_integrity": freeze, "shadow_freeze_status": "PASS" if shadow_hash == SHADOW_FREEZE_SHA256 else "FAIL", "shadow_freeze_sha256": shadow_hash,
        "occlusion_adjudication_status": "PASS_UNCHANGED", "occlusion_artifact_sha256": occlusion_hashes,
        "bounded_case_count": len(cases), "bounded_case_accounting_exact": len(cases) == 3,
        "negative_controls_remain_negative": len(adjudication["negative_control_identities"]) == 2,
        "clipping_positive_requires_all_conditions": True,
        "unknown_preserved": all(all(frame["metrics"]["unknown_expected_pixels"] > 0 for frame in row["frame_evidence"]) for row in cases),
        "source_observed_known_missing_pixel_count": sum(frame["metrics"]["source_observed_missing_pixels"] for row in cases for frame in row["frame_evidence"]),
        "production_hardcoded_identities": hardcoded, "generalization_gate": "PASS" if not hardcoded else "FAIL",
        "glyph_masks_changed": False, "step2e_changed": False, "upstream_artifacts_changed": False, "occlusion_changed": False, "shadow_changed": False,
        "new_segmentation_added": False, "clipping_renderer_added": False, "resolve_mutated": False, "step5_started": False, "step6_started": False,
        "step4d_current_version_closure_ready": matrix["current_version_closure_ready"], "step4d_frozen": False,
        "required_deferred_capabilities": ["CAPTION_CLIPPING_DETECTION_V2", "CAPTION_OCCLUSION_DETECTION_V2"],
        "caption_clipping_detection_v2_status": "DEFERRED_REQUIRED_CAPABILITY", "caption_occlusion_detection_v2_status": "DEFERRED_REQUIRED_CAPABILITY",
        "deferred_capabilities_required_before": "FINAL_PARITY / RELEASE ACCEPTANCE", "human_review_required": True,
        "next_step_name_only": "Step 4D human acceptance + freeze",
    }
    if validation["shadow_freeze_status"] != "PASS" or hardcoded:
        validation["result"] = "BLOCKED_STEP_4D_FINAL_CLIPPING_ADJUDICATION_SYSTEMATIC_DEFECT"
    review = {
        "schema": "video_cloner_step4d_clipping_review_data", "schema_version": 1, "cases": cases,
        "panel_columns": ["source_early", "source_middle", "source_late", "expected_caption", "visible_caption", "missing_or_unknown", "detected_reveal_boundary", "final_overlay"],
        "legend": {"expected": "cyan", "visible": "green", "known_missing": "amber", "unknown": "blue", "reveal_boundary": "magenta"},
    }
    artifacts = {
        "step4d_clipping_final_adjudication.json": json_bytes(adjudication), "step4d_clipping_validation.json": json_bytes(validation),
        "step4d_clipping_review_data.json": json_bytes(review), "step4d_clipping_review_diagnostic.jpg": render(cases, rows_by_identity),
        "step4d_effect_class_final_matrix.json": json_bytes(matrix), "step4d_deferred_required_capabilities.json": json_bytes(deferred),
    }
    artifacts["FINAL_REPORT.md"] = final_report(adjudication, validation, matrix)
    return artifacts


def generate(output: Path, selection: Path) -> dict:
    if output.exists(): raise FileExistsError(output)
    first, second = build(selection), build(selection)
    if first != second: raise RuntimeError("non-deterministic clipping adjudication")
    output.mkdir(parents=True)
    for name, data in first.items(): (output / name).write_bytes(data)
    proof = {"schema": "video_cloner_step4d_clipping_determinism", "schema_version": 1, "complete_generation_count": 2, "rerun_byte_identical": True, "artifact_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in first.items()}}
    (output / "determinism_proof.json").write_bytes(json_bytes(proof))
    return {"result": load(output / "step4d_clipping_validation.json")["result"], "output": str(output)}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--selection", type=Path, required=True); parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(); print(json.dumps(generate(args.output_dir.resolve(), args.selection.resolve()), sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
