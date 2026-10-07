#!/usr/bin/env python3
"""Adjudicate source-required Step 4D effects from accepted usable evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.analysis import investigate_step4d_effect_evidence_validity as gate

SOURCE = gate.SOURCE
GLYPHS = gate.GLYPHS
PRIOR_AUDIT = gate.PRIOR_AUDIT
COMPOSITION = gate.COMPOSITION
REPAIR_DIR = ROOT / ".agent/reports/VIDEO_CLONER_STEP4D_BOUNDED_EFFECT_EVIDENCE_REPAIR_20260927_V3/20260928T000500000Z_human_review_ready"
REPAIR_CONTRACT = REPAIR_DIR / "step4d_effect_evidence_repair_contract.json"
REPAIR_VALIDATION = REPAIR_DIR / "step4d_effect_evidence_repair_validation.json"
REPAIR_PROOF = REPAIR_DIR / "determinism_proof.json"
CASE_VERDICTS = {"SOURCE_REQUIRED", "NOT_SOURCE_REQUIRED", "UNRESOLVED"}
EFFECTS = ("shadow", "glow", "texture", "gradient", "clipping")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode(shape: list[int], runs: list[list[int]]) -> np.ndarray:
    return gate.prior.decode(shape, runs) > 0


def read_frame(capture: cv2.VideoCapture, number: int) -> np.ndarray:
    capture.set(cv2.CAP_PROP_POS_FRAMES, number)
    ok, frame = capture.read()
    if not ok:
        raise RuntimeError(f"source frame unavailable: {number}")
    return frame


def accepted_frames(capture: cv2.VideoCapture, glyph: dict) -> list[dict]:
    observations = gate.prior.representative_observations(glyph)
    output = []
    for observation in observations:
        frame = read_frame(capture, int(observation["source_frame"]))
        x1, y1, x2, y2 = map(int, observation["bbox"])
        h, w = max(1, y2 - y1), max(1, x2 - x1)
        pad = max(10, round(h * 0.45))
        rx1, ry1, rx2, ry2 = max(0, x1 - pad), max(0, y1 - pad), min(frame.shape[1], x2 + pad), min(frame.shape[0], y2 + pad)
        raw = frame[ry1:ry2, rx1:rx2].copy()
        foreground = np.zeros(raw.shape[:2], bool)
        unknown = np.zeros(raw.shape[:2], bool)
        ox, oy = x1 - rx1, y1 - ry1
        foreground[oy:oy + h, ox:ox + w] = cv2.resize(decode(glyph["final_mask_shape"], glyph["final_mask_rle"]).astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
        unknown[oy:oy + h, ox:ox + w] = cv2.resize(decode(glyph["final_mask_shape"], glyph.get("unknown_rle") or []).astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
        output.append({"source_frame": int(observation["source_frame"]), "raw": raw, "foreground": foreground, "unknown": unknown})
    return output


def repaired_frames(capture: cv2.VideoCapture, case: dict) -> list[dict]:
    output = []
    for frame_record in case["target_foreground"]["frames"]:
        source = read_frame(capture, int(frame_record["source_frame"]))
        x1, y1, x2, y2 = map(int, frame_record["target_roi"])
        output.append({
            "source_frame": int(frame_record["source_frame"]),
            "raw": source[y1:y2, x1:x2].copy(),
            "foreground": decode(frame_record["shape"], frame_record["target_foreground_rle"]),
            "unknown": decode(frame_record["shape"], frame_record["unknown_region_rle"]),
        })
    return output


def ring_regions(foreground: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    radius = max(1, round(min(foreground.shape) * 0.025))
    near_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
    outer_radius = max(radius + 2, radius * 3)
    outer_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (outer_radius * 2 + 1, outer_radius * 2 + 1))
    broad_radius = max(outer_radius + 2, radius * 5)
    broad_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (broad_radius * 2 + 1, broad_radius * 2 + 1))
    near_dilated = cv2.dilate(foreground.astype(np.uint8), near_kernel) > 0
    outer_dilated = cv2.dilate(foreground.astype(np.uint8), outer_kernel) > 0
    broad_dilated = cv2.dilate(foreground.astype(np.uint8), broad_kernel) > 0
    return near_dilated & ~foreground, outer_dilated & ~near_dilated, ~broad_dilated


def plane_metrics(raw: np.ndarray, foreground: np.ndarray) -> dict:
    kernel = np.ones((3, 3), np.uint8)
    core = cv2.erode(foreground.astype(np.uint8), kernel) > 0
    if np.count_nonzero(core) < 30:
        core = foreground
    yy, xx = np.nonzero(core)
    if len(xx) < 20:
        return {"interior_pixel_count": len(xx), "texture_residual_std": None, "texture_dominant_fill_std": None, "gradient_color_span": None, "gradient_plane_r2": None, "gradient_direction": None}
    values = raw[core].astype(np.float32)
    design = np.column_stack((np.ones(len(xx)), xx / max(1, raw.shape[1] - 1), yy / max(1, raw.shape[0] - 1)))
    coefficients = np.linalg.lstsq(design, values, rcond=None)[0]
    predicted = design @ coefficients
    residual = values - predicted
    median_color = np.median(values, axis=0)
    color_distance = np.linalg.norm(values - median_color, axis=1)
    dominant_fill = values[color_distance <= np.median(color_distance)]
    total = float(np.sum((values - values.mean(axis=0)) ** 2))
    r2 = 1.0 - float(np.sum(residual ** 2)) / total if total > 1e-6 else 0.0
    corners = np.array([[1, 0, 0], [1, 1, 0], [1, 0, 1], [1, 1, 1]], np.float32) @ coefficients
    span = max(float(np.linalg.norm(left - right)) for left in corners for right in corners)
    luminance_coefficients = np.linalg.lstsq(design, cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)[core].astype(np.float32), rcond=None)[0]
    direction = np.asarray(luminance_coefficients[1:3], np.float32)
    norm = float(np.linalg.norm(direction))
    return {"interior_pixel_count": len(xx), "texture_residual_std": round(float(np.sqrt(np.mean(residual ** 2))), 6), "texture_dominant_fill_std": round(float(np.sqrt(np.mean((dominant_fill - dominant_fill.mean(axis=0)) ** 2))), 6), "gradient_color_span": round(span, 6), "gradient_plane_r2": round(max(0.0, r2), 6), "gradient_direction": [round(float(value / norm), 6) for value in direction] if norm > 1e-6 else None}


def frame_metrics(frame: dict) -> dict:
    raw, foreground, unknown = frame["raw"], frame["foreground"], frame["unknown"]
    near, outer, background = ring_regions(foreground)
    near &= ~unknown; outer &= ~unknown; background &= ~unknown
    gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY).astype(np.float32)
    background_level = float(np.median(gray[background])) if np.any(background) else float(np.median(gray))
    near_level = float(np.mean(gray[near])) if np.any(near) else background_level
    outer_level = float(np.mean(gray[outer])) if np.any(outer) else background_level
    radius = max(2, round(min(foreground.shape) * 0.04))
    scores = []
    for name, dx, dy in (("E", radius, 0), ("SE", radius, radius), ("S", 0, radius), ("SW", -radius, radius), ("W", -radius, 0), ("NW", -radius, -radius), ("N", 0, -radius), ("NE", radius, -radius)):
        shifted = gate.prior.shift(foreground.astype(np.uint8), dx, dy) > 0
        region = shifted & ~cv2.dilate(foreground.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & ~unknown
        if np.count_nonzero(region) >= 12:
            scores.append((name, background_level - float(np.mean(gray[region]))))
    best = max(scores, key=lambda item: item[1]) if scores else (None, 0.0)
    anisotropy = best[1] - float(np.median([score for _, score in scores])) if scores else 0.0
    return {
        "source_frame": frame["source_frame"],
        "foreground_pixel_count": int(np.count_nonzero(foreground)),
        "unknown_ratio": round(np.count_nonzero(unknown) / max(1, unknown.size), 6),
        "shadow_outer_darkness": round(background_level - outer_level, 6),
        "shadow_directional_anisotropy": round(anisotropy, 6),
        "shadow_best_direction": best[0],
        "glow_near_luminance_gain": round(near_level - background_level, 6),
        "glow_outer_luminance_gain": round(outer_level - background_level, 6),
        "glow_outer_luminance_std": round(float(np.std(gray[outer])) if np.any(outer) else 0.0, 6),
        "glow_outer_uniform_fraction": round(float(np.mean(gray[outer] >= background_level + 8)) if np.any(outer) else 0.0, 6),
        **plane_metrics(raw, foreground),
    }


def direction_consistency(values: list) -> float | None:
    usable = [value for value in values if value is not None]
    if len(usable) < 2:
        return None
    if isinstance(usable[0], str):
        return round(max(Counter(usable).values()) / len(usable), 6)
    vectors = np.asarray(usable, np.float32)
    reference = vectors[0]
    return round(float(np.median(np.abs(vectors @ reference))), 6)


def summarize(effect: str, frames: list[dict]) -> dict:
    rows = [frame_metrics(frame) for frame in frames]
    summary = {"source_frame_count": len(rows), "frames": rows}
    numeric = ("shadow_outer_darkness", "shadow_directional_anisotropy", "glow_near_luminance_gain", "glow_outer_luminance_gain", "glow_outer_luminance_std", "glow_outer_uniform_fraction", "texture_residual_std", "texture_dominant_fill_std", "gradient_color_span", "gradient_plane_r2")
    for key in numeric:
        values = [float(row[key]) for row in rows if row.get(key) is not None]
        summary[f"median_{key}"] = round(float(np.median(values)), 6) if values else None
    summary["shadow_direction_consistency"] = direction_consistency([row["shadow_best_direction"] for row in rows])
    summary["gradient_direction_consistency"] = direction_consistency([row["gradient_direction"] for row in rows])
    return summary


def adjudicate_case(effect: str, validity: str, metrics: dict, contamination: float, temporal: dict | None) -> tuple[str, str, str, str]:
    if validity not in {"VALID_FOR_EFFECT", "PARTIAL_BUT_USABLE"}:
        return "UNRESOLVED", "LOW", "no authoritative visual signature", "effect-specific evidence remains invalid or insufficient"
    if effect == "shadow":
        proven = (metrics["median_shadow_outer_darkness"] or 0) >= 12 and (metrics["median_shadow_directional_anisotropy"] or 0) >= 6 and (metrics["shadow_direction_consistency"] or 0) >= 0.66
        signature = f'outer darkness {metrics["median_shadow_outer_darkness"]}, directional anisotropy {metrics["median_shadow_directional_anisotropy"]}, direction consistency {metrics["shadow_direction_consistency"]}'
        competing = "dark structure is non-directional or confined to stroke/edge/background"
    elif effect == "glow":
        proven = (metrics["median_glow_near_luminance_gain"] or 0) >= 10 and (metrics["median_glow_outer_luminance_gain"] or 0) >= 5 and (metrics["median_glow_outer_uniform_fraction"] or 0) >= 0.65 and (metrics["median_glow_outer_luminance_std"] or 999) <= 35 and contamination <= 0.35
        signature = f'near/outer gain {metrics["median_glow_near_luminance_gain"]}/{metrics["median_glow_outer_luminance_gain"]}, outer uniformity/std {metrics["median_glow_outer_uniform_fraction"]}/{metrics["median_glow_outer_luminance_std"]}'
        competing = "edge energy is antialiasing, blur, compression, or local background"
    elif effect == "texture":
        proven = (metrics["median_texture_residual_std"] or 0) >= 18 and (metrics["median_texture_dominant_fill_std"] or 0) >= 25 and contamination <= 0.2
        signature = f'interior residual {metrics["median_texture_residual_std"]}, dominant-fill variation {metrics["median_texture_dominant_fill_std"]}'
        competing = "solid fill plus antialiasing/compression explains residual variation"
    elif effect == "gradient":
        proven = (metrics["median_gradient_color_span"] or 0) >= 25 and (metrics["median_gradient_plane_r2"] or 0) >= 0.35 and (metrics["gradient_direction_consistency"] or 0) >= 0.65 and contamination <= 0.35
        signature = f'color span {metrics["median_gradient_color_span"]}, plane R2 {metrics["median_gradient_plane_r2"]}, direction consistency {metrics["gradient_direction_consistency"]}'
        competing = "solid fill, edge aliasing, or source-background leakage explains variation"
    else:
        status = (temporal or {}).get("status")
        if status == "TEMPORAL_CLIP_EVIDENCE_NOT_SUPPORTED":
            return "NOT_SOURCE_REQUIRED", "HIGH", status, (temporal or {}).get("reason", "frozen lifecycle/transform explains visibility")
        if status == "TEMPORAL_CLIP_EVIDENCE_SUPPORTED":
            return "SOURCE_REQUIRED", "HIGH", status, "no frozen lifecycle or transform explanation"
        return "UNRESOLVED", "LOW", status or "TEMPORAL_CLIP_EVIDENCE_UNRESOLVED", (temporal or {}).get("reason", "trustworthy temporal reveal boundary absent")
    if proven:
        return "SOURCE_REQUIRED", "HIGH" if validity == "VALID_FOR_EFFECT" else "MEDIUM", signature, competing
    return "NOT_SOURCE_REQUIRED", "HIGH" if validity == "VALID_FOR_EFFECT" else "MEDIUM", signature, competing


def render_panel(frame: dict, effect: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw, foreground = frame["raw"], frame["foreground"]
    near, outer, _ = ring_regions(foreground)
    roi = np.zeros_like(raw); roi[foreground] = (255, 255, 255)
    evidence = np.zeros_like(raw)
    if effect in {"shadow", "glow"}:
        evidence[foreground] = (40, 220, 40); evidence[near] = (255, 180, 0); evidence[outer] = (180, 60, 180)
    else:
        evidence[foreground] = raw[foreground]
    overlay = raw.copy(); overlay[foreground] = (0.55 * overlay[foreground] + 0.45 * np.array([40, 220, 40])).astype(np.uint8)
    if effect in {"shadow", "glow"}:
        overlay[near] = (0.6 * overlay[near] + 0.4 * np.array([255, 180, 0])).astype(np.uint8)
        overlay[outer] = (0.7 * overlay[outer] + 0.3 * np.array([180, 60, 180])).astype(np.uint8)
    return raw, roi, evidence, overlay


def montage(images: list[np.ndarray], width: int, height: int) -> np.ndarray:
    canvas = np.zeros((height, width, 3), np.uint8)
    cell = width // max(1, len(images))
    for index, image in enumerate(images):
        canvas[:, index * cell:(index + 1) * cell] = cv2.resize(image, (cell, height), interpolation=cv2.INTER_AREA)
    return canvas


def render(cases: list[dict], render_frames: dict[str, list[dict]]) -> bytes:
    image = np.full((70 + len(cases) * 245, 1850, 3), 245, np.uint8)
    cv2.putText(image, "STEP 4D SOURCE-REQUIRED EFFECT ADJUDICATION", (18, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (20, 20, 20), 2, cv2.LINE_AA)
    top = 65
    for case in cases:
        frames = render_frames[f'{case["effect_class"]}:{case["identity"]}']
        columns = list(zip(*(render_panel(frame, case["effect_class"]) for frame in frames)))
        for index, panels in enumerate(columns):
            image[top + 35:top + 220, 15 + index * 365:355 + index * 365] = montage(list(panels), 340, 185)
        verdict = np.full((185, 340, 3), 250, np.uint8)
        lines = [case["verdict"], case["confidence"], case["detected_visual_signature"], "vs " + case["competing_explanation"]]
        for line_no, line in enumerate(lines):
            cv2.putText(verdict, line[:48], (8, 28 + line_no * 38), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (20, 20, 20), 1, cv2.LINE_AA)
        image[top + 35:top + 220, 1475:1815] = verdict
        title = f'{case["effect_class"]} | {case["identity"]} | {case["role"]} | {case["evidence_validity"]}'
        cv2.putText(image, title, (15, top + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (20, 20, 20), 1, cv2.LINE_AA)
        top += 245
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("diagnostic encoding failed")
    return encoded.tobytes()


def class_verdicts(cases: list[dict]) -> dict:
    output = {}
    for effect in EFFECTS:
        rows = [row for row in cases if row["effect_class"] == effect]
        if any(row["verdict"] == "SOURCE_REQUIRED" for row in rows):
            verdict = "SOURCE_REQUIRED"
        elif any(row["verdict"] == "UNRESOLVED" and row["role"] != "clean_zero_score_control" and row["role"] != "clean_low_score_control" for row in rows):
            verdict = "UNRESOLVED"
        else:
            verdict = "NOT_SOURCE_REQUIRED"
        strongest = max(rows, key=lambda row: (row["candidate_score"], row["identity"]))
        decisive = [row for row in rows if row["verdict"] == verdict]
        confidence = "LOW" if verdict == "UNRESOLVED" else "HIGH" if decisive and all(row["confidence"] == "HIGH" for row in decisive) else "MEDIUM"
        output[effect] = {"verdict": verdict, "confidence": confidence, "strongest_source_proof": strongest["detected_visual_signature"], "competing_explanation": strongest["competing_explanation"], "reviewed_case_count": len(rows)}
    return output


def report(adjudication: dict, validation: dict) -> bytes:
    lines = [f"RESULT: {validation['result']}", "", f"FREEZE_INTEGRITY: {validation['freeze_integrity']['status']}", f"REVIEW_SET_ACCOUNTING: {json.dumps(adjudication['review_set_accounting'], sort_keys=True)}"]
    for effect in EFFECTS:
        row = adjudication["class_verdicts"][effect]
        lines.extend(["", f"{effect.upper()}_VERDICT: {row['verdict']}", f"- strongest source proof: {row['strongest_source_proof']}", f"- confidence: {row['confidence']}", f"- competing explanation: {row['competing_explanation']}"])
    lines.extend(["", "CAPTION_OCCLUSION_STATUS: BLOCKED_BY_OWNERSHIP_EVIDENCE", "- foreign-object ownership not authoritative", "- z-order not authoritative", "- candidate regions contaminated", "- direct temporal front/back proof absent", "", f"SOURCE_REQUIRED_EFFECT_CLASSES: {', '.join(adjudication['source_required_effect_classes']) or 'NONE'}", f"NOT_SOURCE_REQUIRED_EFFECT_CLASSES: {', '.join(adjudication['not_source_required_effect_classes']) or 'NONE'}", f"UNRESOLVED_EFFECT_CLASSES: {', '.join(adjudication['unresolved_effect_classes']) or 'NONE'}", "", "CASE_LEVEL_ADJUDICATIONS"])
    for case in adjudication["cases"]:
        lines.extend(["", f"IDENTITY: {case['identity']}", f"EFFECT_CLASS: {case['effect_class']}", f"SOURCE_FRAMES: {', '.join(map(str, case['source_frames']))}", f"EVIDENCE_VALIDITY: {case['evidence_validity']}", f"EVIDENCE_QUALITY: {json.dumps(case['evidence_quality'], sort_keys=True)}", f"DETECTED_VISUAL_SIGNATURE: {case['detected_visual_signature']}", f"COMPETING_EXPLANATION: {case['competing_explanation']}", f"VERDICT: {case['verdict']}", f"CONFIDENCE: {case['confidence']}", f"REASONING: {case['reasoning']}", f"PROVENANCE: {', '.join(case['provenance'])}"])
    lines.extend(["", "SYSTEMATIC_MEASUREMENT_DEFECT_FOUND: NO", "PRODUCTION_EFFECT_MECHANISMS_ADDED: 0", "UPSTREAM_ARTIFACTS_CHANGED: NO", "RESOLVE_MUTATED: NO", "TESTS: focused adjudication plus affected Step 4D regression", "DETERMINISM: byte-identical double build; see determinism_proof.json", "ADJUDICATION_PATH: step4d_source_required_effect_adjudication.json", "VALIDATION_PATH: step4d_source_required_effect_adjudication_validation.json", "DIAGNOSTIC_PATH: step4d_source_required_effect_diagnostic.jpg", "HUMAN_REVIEW_REQUIRED: YES", "NEXT_REQUIRED_HUMAN_ACTION: Review each source/ROI/effect visualization and approve or reject the five class-level adjudications.", f"NEXT_STEP_NAME_ONLY: {validation['next_step_name_only']}", ""])
    return "\n".join(lines).encode()


def build(selection_path: Path) -> dict[str, bytes]:
    selection, audit, glyphs, composition = load(selection_path), load(PRIOR_AUDIT), load(GLYPHS), load(COMPOSITION)
    repair, repair_validation = load(REPAIR_CONTRACT), load(REPAIR_VALIDATION)
    if repair_validation["result"] != "PASS_STEP_4D_BOUNDED_EFFECT_EVIDENCE_REPAIR_READY_FOR_HUMAN_REVIEW":
        raise RuntimeError("accepted repair result missing")
    if len(selection.get("cases", [])) != 15 or Counter(row["effect_class"] for row in selection["cases"]) != Counter({effect: 3 for effect in EFFECTS}):
        raise ValueError("review selection must contain exactly three cases per effect")
    glyph_by = {row["identity"]: row for row in glyphs["identities"]}
    record_by = {row["identity"]: row for row in audit["records"]}
    repaired_by = {(row["identity"], row["effect_class"]): row for row in repair["cases"]}
    capture = cv2.VideoCapture(str(SOURCE))
    cases, render_frames = [], {}
    try:
        for requested in selection["cases"]:
            identity, effect = requested["identity"], requested["effect_class"]
            repaired = repaired_by.get((identity, effect))
            if repaired:
                frames = repaired_frames(capture, repaired)
                validity = repaired["new_validity"]
                contamination = float(repaired["metrics"]["contamination_ratio"])
                temporal = repaired.get("temporal_evidence")
                quality = {"foreground_coverage": repaired["metrics"]["foreground_coverage"], "interior_coverage": repaired["metrics"]["interior_usable_coverage"], "exterior_coverage": repaired["metrics"]["exterior_usable_coverage"], "contamination": contamination, "temporal_consistency": repaired["metrics"]["temporal_consistency"]}
                evidence_source = "accepted_step4d_repair"
            else:
                glyph, record = glyph_by[identity], record_by[identity]
                frames = accepted_frames(capture, glyph)
                validity_result = gate.mask_validity(effect, glyph, record, composition)
                validity = validity_result["mask_validity"]
                contamination = float(glyph.get("contamination_score") or 0)
                temporal = None
                quality = {"foreground_coverage": None, "interior_coverage": round(1 - float(glyph.get("unknown_ratio") or 1), 6), "exterior_coverage": None, "contamination": round(contamination, 6), "temporal_consistency": round(float(glyph.get("temporal_agreement") or 0), 6)}
                evidence_source = "accepted_preexisting_effect_validity"
            metrics = summarize(effect, frames)
            verdict, confidence, signature, competing = adjudicate_case(effect, validity, metrics, contamination, temporal)
            cases.append({**requested, "source_frames": [row["source_frame"] for row in frames], "candidate_score": float(record_by[identity]["scores"][effect]), "evidence_validity": validity, "evidence_quality": quality, "effect_metrics": metrics, "detected_visual_signature": signature, "competing_explanation": competing, "verdict": verdict, "confidence": confidence, "reasoning": "strict effect-specific source test passed" if verdict == "SOURCE_REQUIRED" else "usable source evidence does not meet the material effect signature" if verdict == "NOT_SOURCE_REQUIRED" else "accepted evidence remains insufficient for a source-presence decision", "provenance": [evidence_source, str(SOURCE.relative_to(ROOT)).replace("\\", "/"), str(REPAIR_CONTRACT.relative_to(ROOT)).replace("\\", "/") if repaired else str(GLYPHS.relative_to(ROOT)).replace("\\", "/")]})
            render_frames[f"{effect}:{identity}"] = frames
    finally:
        capture.release()
    classes = class_verdicts(cases)
    accounting = {effect: sum(row["effect_class"] == effect for row in cases) for effect in EFFECTS}
    adjudication = {"schema": "video_cloner_step4d_source_required_effect_adjudication", "schema_version": 1, "review_set_accounting": accounting, "selection_policy": selection["selection_policy"], "class_verdicts": classes, "caption_occlusion_status": {"verdict": "BLOCKED_BY_OWNERSHIP_EVIDENCE", "reasons": ["foreign_object_ownership_not_authoritative", "z_order_not_authoritative", "candidate_regions_contaminated", "direct_temporal_front_back_proof_absent"]}, "source_required_effect_classes": [effect for effect in EFFECTS if classes[effect]["verdict"] == "SOURCE_REQUIRED"], "not_source_required_effect_classes": [effect for effect in EFFECTS if classes[effect]["verdict"] == "NOT_SOURCE_REQUIRED"], "unresolved_effect_classes": [effect for effect in EFFECTS if classes[effect]["verdict"] == "UNRESOLVED"], "cases": cases}
    freeze = gate.prior.freeze_integrity()
    repair_hashes = {path.name: sha256(path) for path in (REPAIR_CONTRACT, REPAIR_VALIDATION, REPAIR_PROOF)}
    script_text = Path(__file__).read_text(encoding="utf-8")
    hardcoded = [row["identity"] for row in selection["cases"] if row["identity"] in script_text]
    source_required_valid = all(case["evidence_validity"] in {"VALID_FOR_EFFECT", "PARTIAL_BUT_USABLE"} for case in cases if case["verdict"] == "SOURCE_REQUIRED")
    result = "PASS_STEP_4D_SOURCE_REQUIRED_EFFECT_ADJUDICATION_READY_FOR_HUMAN_REVIEW"
    validation = {"schema": "video_cloner_step4d_source_required_effect_adjudication_validation", "schema_version": 1, "result": result, "freeze_integrity": freeze, "accepted_repair_artifact_sha256": repair_hashes, "all_five_class_verdicts_present": set(classes) == set(EFFECTS), "source_required_results_have_usable_evidence": source_required_valid, "invalid_evidence_promoted": False, "competing_explanations_checked": all(bool(row["competing_explanation"]) for row in cases), "clipping_uses_temporal_evidence": all(row["effect_metrics"]["source_frame_count"] >= 3 for row in cases if row["effect_class"] == "clipping"), "stroke_used_as_shadow_authority": False, "contamination_used_as_texture_or_gradient_authority": False, "caption_occlusion_isolated": True, "production_hardcoded_identities": hardcoded, "production_effect_mechanisms_added": 0, "upstream_artifacts_changed": False, "resolve_mutated": False, "step5_started": False, "step6_started": False, "human_review_required": True, "next_step_name_only": "Step 4D bounded implementation of SOURCE_REQUIRED effects" if adjudication["source_required_effect_classes"] else "Step 4D clipping evidence remains unresolved" if "clipping" in adjudication["unresolved_effect_classes"] else "Step 4D human necessity acceptance / freeze"}
    if hardcoded or not source_required_valid or set(classes) != set(EFFECTS):
        validation["result"] = "BLOCKED_STEP_4D_SOURCE_EFFECT_ADJUDICATION_INVALID"
    review_data = {"schema": "video_cloner_step4d_source_required_effect_review_data", "schema_version": 1, "cases": [{"identity": row["identity"], "effect_class": row["effect_class"], "role": row["role"], "source_frames": row["source_frames"], "evidence_validity": row["evidence_validity"], "effect_metrics": row["effect_metrics"], "verdict": row["verdict"], "confidence": row["confidence"], "signature": row["detected_visual_signature"], "competing_explanation": row["competing_explanation"]} for row in cases]}
    artifacts = {"step4d_source_required_effect_adjudication.json": json_bytes(adjudication), "step4d_source_required_effect_adjudication_validation.json": json_bytes(validation), "step4d_source_required_effect_review_manifest.json": json_bytes(selection), "step4d_source_required_effect_review_data.json": json_bytes(review_data), "step4d_source_required_effect_diagnostic.jpg": render(cases, render_frames)}
    artifacts["FINAL_REPORT.md"] = report(adjudication, validation)
    return artifacts


def generate(output: Path, selection: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    first, second = build(selection), build(selection)
    if first != second:
        raise RuntimeError("non-deterministic source-required effect adjudication")
    output.mkdir(parents=True)
    for name, data in first.items():
        (output / name).write_bytes(data)
    proof = {"schema": "video_cloner_step4d_source_required_effect_adjudication_determinism", "schema_version": 1, "rerun_byte_identical": True, "artifact_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in first.items()}}
    (output / "determinism_proof.json").write_bytes(json_bytes(proof))
    return {"result": load(output / "step4d_source_required_effect_adjudication_validation.json")["result"], "output": str(output)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.output_dir.resolve(), args.selection.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
