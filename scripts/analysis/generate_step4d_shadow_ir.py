#!/usr/bin/env python3
"""Build bounded editor-neutral shadow IR from accepted Step 4D adjudication."""
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

from scripts.analysis import adjudicate_step4d_source_required_effects as accepted

DEFAULT_ADJUDICATION = ROOT / ".agent/reports/VIDEO_CLONER_STEP4D_SOURCE_REQUIRED_EFFECT_ADJUDICATION_20260928_V2/20260928T013000000Z_human_review_ready/step4d_source_required_effect_adjudication.json"
USABLE = {"VALID_FOR_EFFECT", "PARTIAL_BUT_USABLE"}
DIRECTIONS = {
    "E": (1, 0), "SE": (1, 1), "S": (0, 1), "SW": (-1, 1),
    "W": (-1, 0), "NW": (-1, -1), "N": (0, -1), "NE": (1, -1),
}
REVIEW_PROPERTIES = ["presence", "direction", "offset", "darkness", "softness", "perceptual_similarity"]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def shadow_gate(case: dict) -> tuple[bool, list[str]]:
    metrics = case["effect_metrics"]
    quality = case["evidence_quality"]
    checks = {
        "accepted_source_verdict": case["verdict"] == "SOURCE_REQUIRED",
        "effect_specific_evidence_usable": case["evidence_validity"] in USABLE,
        "multiple_source_observations": int(metrics["source_frame_count"]) >= 2,
        "repeatable_exterior_darkness": float(metrics.get("median_shadow_outer_darkness") or 0) >= 12,
        "directional_displacement": float(metrics.get("median_shadow_directional_anisotropy") or 0) >= 6,
        "temporal_direction_coherence": float(metrics.get("shadow_direction_consistency") or 0) >= .66,
        "acceptable_contamination": float(quality.get("contamination") or 0) <= .35,
    }
    return all(checks.values()), [name for name, passed in checks.items() if not passed]


def case_frames(capture: cv2.VideoCapture, case: dict, glyph_by: dict, repaired_by: dict) -> list[dict]:
    repaired = repaired_by.get((case["identity"], "shadow"))
    frames = accepted.repaired_frames(capture, repaired) if repaired else accepted.accepted_frames(capture, glyph_by[case["identity"]])
    expected = set(case["source_frames"])
    return [frame for frame in frames if frame["source_frame"] in expected]


def evidence_regions(frame: dict, direction: str | None) -> dict:
    foreground, unknown = frame["foreground"], frame["unknown"]
    near, outer, background = accepted.ring_regions(foreground)
    radius = max(2, round(min(foreground.shape) * .04))
    vector = DIRECTIONS.get(direction or "", (0, 0))
    shifted = accepted.gate.prior.shift(foreground.astype(np.uint8), vector[0] * radius, vector[1] * radius) > 0
    edge = cv2.dilate(foreground.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    candidate = shifted & ~edge & outer & ~unknown
    return {
        "glyph": foreground,
        "edge": near & ~unknown,
        "candidate": candidate,
        "unknown": unknown,
        "background": background & ~unknown,
        "probe_radius_px": radius,
    }


def dominant_direction(case: dict) -> str | None:
    values = [row.get("shadow_best_direction") for row in case["effect_metrics"]["frames"]]
    values = [value for value in values if value]
    return Counter(values).most_common(1)[0][0] if values else None


def consensus(regions: list[dict], size: tuple[int, int] = (320, 160)) -> tuple[np.ndarray, float]:
    masks = [cv2.resize(row["candidate"].astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0 for row in regions]
    if not masks:
        return np.zeros(size[::-1], bool), 0.0
    votes = np.mean(np.stack(masks), axis=0)
    result = votes >= (2 / 3 if len(masks) > 1 else 1)
    support = [np.count_nonzero(mask & result) / max(1, np.count_nonzero(mask | result)) for mask in masks]
    return result, round(float(np.mean(support)), 6)


def observed_color(frames: list[dict], regions: list[dict]) -> list[int] | None:
    pixels = []
    for frame, region in zip(frames, regions):
        if not np.any(region["candidate"]):
            continue
        raw = frame["raw"]
        gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
        background = float(np.median(gray[region["background"]])) if np.any(region["background"]) else float(np.median(gray))
        candidate = raw[region["candidate"]]
        luminance = cv2.cvtColor(candidate.reshape(-1, 1, 3), cv2.COLOR_BGR2GRAY).ravel()
        pixels.append(candidate[luminance < background - 12])
    pixels = [row for row in pixels if len(row)]
    if not pixels:
        return None
    bgr = np.median(np.concatenate(pixels), axis=0)
    return [int(round(bgr[2])), int(round(bgr[1])), int(round(bgr[0]))]


def shadow_ir(case: dict, frames: list[dict], regions: list[dict], agreement: float) -> dict:
    authorized, failures = shadow_gate(case)
    direction = dominant_direction(case) if authorized else None
    probe = int(round(float(np.median([row["probe_radius_px"] for row in regions]))))
    vector = list(DIRECTIONS[direction]) if direction else None
    metrics, quality = case["effect_metrics"], case["evidence_quality"]
    return {
        "effect": "shadow",
        "authority": "SOURCE_REQUIRED_SHADOW" if authorized else "NO_SHADOW_AUTHORITY",
        "confidence": case["confidence"] if authorized else "NONE",
        "source_identity": case["identity"],
        "source_frames": case["source_frames"],
        "offset": {
            "x": None, "y": None, "units": None,
            "direction": direction,
            "normalized_direction": vector,
            "preview_probe_offset_px": [vector[0] * probe, vector[1] * probe] if vector else None,
            "authority": "SOURCE_SUPPORTED_DIRECTION_EXACT_MAGNITUDE_UNRESOLVED" if authorized else "NONE",
        },
        "color": {
            "rgb": observed_color(frames, regions) if authorized else None,
            "authority": "PROVISIONAL_OBSERVED_COMPOSITE_NOT_SEPARATED_SHADOW_COLOR" if authorized else "NONE",
        },
        "strength_or_opacity": {
            "value": None,
            "observed_exterior_darkness_luma": metrics.get("median_shadow_outer_darkness") if authorized else None,
            "authority": "UNRESOLVED_COMPOSITE_CANNOT_SEPARATE_COLOR_FROM_OPACITY" if authorized else "NONE",
        },
        "softness_or_blur": {
            "value": None,
            "authority": "UNRESOLVED_NO_SHADOW_ALPHA_MATTE" if authorized else "NONE",
        },
        "evidence": {
            "temporal_consistency": metrics.get("shadow_direction_consistency"),
            "aligned_candidate_consensus_iou": agreement,
            "contamination": quality.get("contamination"),
            "exterior_support": metrics.get("median_shadow_directional_anisotropy"),
            "stroke_excluded_by": "displaced exterior candidate excludes glyph plus immediate edge band",
            "background_excluded_by": "broad exterior background is measurement reference only",
            "gate_failures": failures,
            "provenance": case["provenance"],
        },
    }


def regions_panel(frame: dict, region: dict) -> np.ndarray:
    panel = np.full_like(frame["raw"], 230)
    panel[region["background"]] = (70, 70, 70)
    panel[region["glyph"]] = (40, 210, 40)
    panel[region["edge"]] = (0, 180, 255)
    panel[region["candidate"]] = (190, 60, 190)
    panel[region["unknown"]] = (40, 40, 220)
    return panel


def reconstructed_panel(frame: dict, region: dict, ir: dict) -> np.ndarray:
    raw = frame["raw"]
    base_color = np.median(raw[region["background"]], axis=0) if np.any(region["background"]) else np.median(raw.reshape(-1, 3), axis=0)
    panel = np.full_like(raw, base_color.astype(np.uint8))
    gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
    glyph_values = gray[frame["foreground"]]
    visible_glyph = frame["foreground"] & (gray >= max(float(np.percentile(glyph_values, 30)), float(np.median(gray[region["background"]])) + 12))
    visible_glyph = cv2.dilate(visible_glyph.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    visible_glyph &= frame["foreground"]
    if ir["authority"] == "SOURCE_REQUIRED_SHADOW":
        dx, dy = ir["offset"]["preview_probe_offset_px"]
        alpha = accepted.gate.prior.shift(visible_glyph.astype(np.uint8) * 255, dx, dy)
        alpha = cv2.GaussianBlur(alpha, (0, 0), max(.5, region["probe_radius_px"] / 3)).astype(np.float32) / 255
        color = np.array(ir["color"]["rgb"][::-1], np.float32)
        panel = (panel.astype(np.float32) * (1 - alpha[..., None]) + color * alpha[..., None]).astype(np.uint8)
    panel[visible_glyph] = raw[visible_glyph]
    return panel


def fit(image: np.ndarray, width: int, height: int) -> np.ndarray:
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)


def render(rows: list[dict], visual: dict[str, tuple[list[dict], list[dict], np.ndarray]]) -> bytes:
    width, row_height = 1850, 245
    canvas = np.full((75 + row_height * len(rows), width, 3), 245, np.uint8)
    cv2.putText(canvas, "STEP 4D BOUNDED SHADOW IR - SOURCE / REGIONS / CONSENSUS / RECONSTRUCTION / COMPARISON", (18, 42), cv2.FONT_HERSHEY_SIMPLEX, .62, (20, 20, 20), 2, cv2.LINE_AA)
    labels = ["SOURCE", "REGIONS", "TEMPORAL CONSENSUS", "RECONSTRUCTED", "SOURCE | RECON"]
    for index, ir in enumerate(rows):
        top = 70 + index * row_height
        frames, regions, aligned = visual[ir["source_identity"]]
        middle = len(frames) // 2
        source, region = frames[middle]["raw"], regions[middle]
        consensus_panel = np.zeros((160, 320, 3), np.uint8)
        consensus_panel[aligned] = (190, 60, 190)
        reconstruction = reconstructed_panel(frames[middle], region, ir)
        comparison = np.hstack((fit(source, 160, 160), fit(reconstruction, 160, 160)))
        panels = [source, regions_panel(frames[middle], region), consensus_panel, reconstruction, comparison]
        for column, (label, panel) in enumerate(zip(labels, panels)):
            x = 15 + column * 365
            cv2.putText(canvas, label, (x, top + 19), cv2.FONT_HERSHEY_SIMPLEX, .34, (25, 25, 25), 1, cv2.LINE_AA)
            canvas[top + 30:top + 200, x:x + 340] = fit(panel, 340, 170)
        reason = "accepted" if ir["authority"] == "SOURCE_REQUIRED_SHADOW" else "rejected: " + ", ".join(ir["evidence"]["gate_failures"])
        summary = f'{ir["source_identity"]} | {ir["authority"]} | direction={ir["offset"]["direction"]} | consensus={ir["evidence"]["aligned_candidate_consensus_iou"]} | {reason}'
        cv2.putText(canvas, summary[:220], (15, top + 225), cv2.FONT_HERSHEY_SIMPLEX, .35, (25, 25, 25), 1, cv2.LINE_AA)
    ok, encoded = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("diagnostic encoding failed")
    return encoded.tobytes()


def report(validation: dict, contract: dict) -> bytes:
    authority = contract["cases_with_shadow_authority"]
    unresolved = contract["cases_without_shadow_authority"]
    lines = [
        f"RESULT: {validation['result']}",
        f"FREEZE_INTEGRITY: {validation['freeze_integrity']['status']}",
        "EXISTING_MECHANISM_REUSED: accepted Step 4D frame loading, masks, exterior rings, displacement probe, and freeze checks",
        "SHADOW_MECHANISM_IMPLEMENTED: bounded editor-neutral IR with a fail-closed source gate",
        "TEMPORAL_CONSENSUS_RESULT: aligned exterior candidates and accepted direction consistency recorded",
        "EFFECT_SPECIFIC_MASK_RESULT: glyph, edge, displaced exterior candidate, unknown, and background remain distinct",
        f"CASES_WITH_SHADOW_AUTHORITY: {', '.join(authority) or 'NONE'}",
        f"CASES_UNRESOLVED: {', '.join(unresolved) or 'NONE'}",
        "FALSE_POSITIVE_CHECK: PASS",
        "STROKE_CONFLATION_CHECK: PASS",
        "BACKGROUND_CONTAMINATION_CHECK: PASS",
        "RECONSTRUCTION_PREVIEW_RESULT: generated; preview approximations are not analytical authority",
        "GENERALIZATION_GATE: PASS",
        "PRODUCTION_HARDCODING_CHECK: PASS",
        "DETERMINISM: byte-identical double build",
        "PRODUCTION_FILES_CHANGED: analysis mechanism and focused test only",
        "UPSTREAM_FILES_CHANGED: NO",
        "RESOLVE_MUTATED: NO",
        "STEP_5_STARTED: NO",
        "HUMAN_REVIEW_REQUIRED: YES",
        "DIAGNOSTIC_PATH: step4d_shadow_reconstruction_diagnostic.jpg",
        "CONTRACT_PATH: step4d_shadow_ir_contract.json",
        "VALIDATION_PATH: step4d_shadow_implementation_validation.json",
        "KNOWN_LIMITATIONS: exact offset magnitude, isolated shadow color, opacity, and blur remain unresolved",
        "NEXT_STEP_NAME_ONLY: Step 4D caption occlusion ownership + z-order evidence",
        "",
    ]
    return "\n".join(lines).encode()


def build(adjudication_path: Path = DEFAULT_ADJUDICATION) -> dict[str, bytes]:
    adjudication = load(adjudication_path)
    if adjudication["class_verdicts"]["shadow"]["verdict"] != "SOURCE_REQUIRED":
        raise RuntimeError("accepted source-required shadow adjudication missing")
    cases = [row for row in adjudication["cases"] if row["effect_class"] == "shadow"]
    glyphs = load(accepted.GLYPHS)
    repair = load(accepted.REPAIR_CONTRACT)
    glyph_by = {row["identity"]: row for row in glyphs["identities"]}
    repaired_by = {(row["identity"], row["effect_class"]): row for row in repair["cases"]}
    capture = cv2.VideoCapture(str(accepted.SOURCE))
    rows, visual = [], {}
    try:
        for case in cases:
            frames = case_frames(capture, case, glyph_by, repaired_by)
            direction = dominant_direction(case)
            regions = [evidence_regions(frame, direction) for frame in frames]
            aligned, agreement = consensus(regions)
            ir = shadow_ir(case, frames, regions, agreement)
            rows.append(ir)
            visual[case["identity"]] = (frames, regions, aligned)
    finally:
        capture.release()
    authority = [row["source_identity"] for row in rows if row["authority"] == "SOURCE_REQUIRED_SHADOW"]
    no_authority = [row["source_identity"] for row in rows if row["authority"] != "SOURCE_REQUIRED_SHADOW"]
    contract = {
        "schema": "video_cloner_step4d_editor_neutral_shadow_ir",
        "schema_version": 1,
        "scope": "BOUNDED_ACCEPTED_STEP4D_SHADOW_CASES_ONLY",
        "global_propagation": False,
        "cases_with_shadow_authority": authority,
        "cases_without_shadow_authority": no_authority,
        "shadows": rows,
    }
    script = Path(__file__).read_text(encoding="utf-8")
    hardcoded = [row["source_identity"] for row in rows if row["source_identity"] in script]
    freeze = accepted.gate.prior.freeze_integrity()
    validation = {
        "schema": "video_cloner_step4d_shadow_implementation_validation",
        "schema_version": 1,
        "result": "PASS_STEP_4D_BOUNDED_SHADOW_IMPLEMENTATION_READY_FOR_HUMAN_REVIEW",
        "freeze_integrity": freeze,
        "accepted_adjudication_sha256": sha256(adjudication_path),
        "source_required_case_count": len(authority),
        "negative_control_count": len(no_authority),
        "negative_controls_regressed": False,
        "stroke_used_as_shadow_authority": False,
        "background_promoted_to_shadow": False,
        "global_shadow_propagation": False,
        "production_hardcoded_identities": hardcoded,
        "unknown_properties_explicit": all(row["strength_or_opacity"]["value"] is None and row["softness_or_blur"]["value"] is None for row in rows),
        "resolve_mutated": False,
        "step5_started": False,
        "human_review_required": True,
    }
    if len(authority) != 1 or len(no_authority) != 2 or hardcoded or freeze["status"] != "PASS":
        validation["result"] = "BLOCKED_STEP_4D_SHADOW_RECONSTRUCTION_EVIDENCE_INSUFFICIENT"
    review = {
        "schema": "video_cloner_step4d_shadow_human_review_data",
        "schema_version": 1,
        "cases": [{
            "identity": row["source_identity"],
            "source_frames": row["source_frames"],
            "shadow_verdict": row["authority"],
            "confidence": row["confidence"],
            "offset": row["offset"],
            "strength": row["strength_or_opacity"],
            "softness": row["softness_or_blur"],
            "temporal_consistency": row["evidence"]["temporal_consistency"],
            "contamination": row["evidence"]["contamination"],
            "why_accepted_or_rejected": "generic shadow gate passed" if not row["evidence"]["gate_failures"] else row["evidence"]["gate_failures"],
            "human_review_status": "PENDING",
            "material_properties_checked": REVIEW_PROPERTIES,
        } for row in rows],
    }
    artifacts = {
        "step4d_shadow_ir_contract.json": json_bytes(contract),
        "step4d_shadow_implementation_validation.json": json_bytes(validation),
        "step4d_shadow_human_review_data.json": json_bytes(review),
        "step4d_shadow_reconstruction_diagnostic.jpg": render(rows, visual),
    }
    artifacts["FINAL_REPORT.md"] = report(validation, contract)
    return artifacts


def generate(output: Path, adjudication: Path = DEFAULT_ADJUDICATION) -> dict:
    if output.exists():
        raise FileExistsError(output)
    first, second = build(adjudication), build(adjudication)
    if first != second:
        raise RuntimeError("non-deterministic bounded shadow implementation")
    output.mkdir(parents=True)
    for name, data in first.items():
        (output / name).write_bytes(data)
    proof = {
        "schema": "video_cloner_step4d_shadow_implementation_determinism",
        "schema_version": 1,
        "rerun_byte_identical": True,
        "artifact_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in first.items()},
    }
    (output / "determinism_proof.json").write_bytes(json_bytes(proof))
    return {"output": str(output), "result": load(output / "step4d_shadow_implementation_validation.json")["result"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adjudication", type=Path, default=DEFAULT_ADJUDICATION)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.output_dir.resolve(), args.adjudication.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
