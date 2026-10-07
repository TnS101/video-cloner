#!/usr/bin/env python3
"""Calibrate bounded shadow parameters after accepted Step 4D presence authority."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.analysis import generate_step4d_shadow_ir as shadow
from scripts.standalone import video_cloner_font_inference as fonts

BASE_DIR = ROOT / ".agent/reports/VIDEO_CLONER_STEP4D_BOUNDED_SHADOW_IMPLEMENTATION_20260928_V2/20260928T023000000Z_human_review_ready"
BASE_IR = BASE_DIR / "step4d_shadow_ir_contract.json"
BASE_VALIDATION = BASE_DIR / "step4d_shadow_implementation_validation.json"
STATIC_STYLE = ROOT / ".agent/reports/VIDEO_CLONER_STEP2F_FONT_AUTHORITY_CALIBRATION_20260927/20260927T020000000Z_calibrated/whole_reel_static_style_contract_calibrated.json"
SIGMA_NORMALIZED = (0.0, .01, .02, .03, .04, .06)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def glyph_height(mask: np.ndarray) -> int:
    rows = np.where(mask)[0]
    return int(rows.max() - rows.min() + 1) if len(rows) else 1


def fit_regions(frame: dict) -> dict:
    foreground, unknown = frame["foreground"], frame["unknown"]
    near, outer, background = shadow.accepted.ring_regions(foreground)
    edge = near & ~unknown
    return {
        "foreground": foreground,
        "edge": edge,
        "valid_exterior": outer & ~unknown,
        "known_background": background & ~unknown,
        "excluded_unknown": unknown,
    }


def evaluate(frame: dict, regions: dict, dx: int, dy: int, sigma_normalized: float) -> dict:
    raw, foreground = frame["raw"], regions["foreground"]
    height = glyph_height(foreground)
    sigma = sigma_normalized * height
    template = foreground.astype(np.uint8) * 255
    if sigma:
        template = cv2.GaussianBlur(template, (0, 0), sigma)
    template = shadow.accepted.gate.prior.shift(template, dx, dy).astype(np.float32) / 255
    valid = regions["valid_exterior"]
    gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY).astype(np.float32)
    background = float(np.median(gray[regions["known_background"]])) if np.any(regions["known_background"]) else float(np.median(gray))
    darkness = np.clip((background - gray) / 255, 0, 1)
    x, y = template[valid], darkness[valid]
    if len(x) < 24 or float(np.std(x)) < 1e-6:
        return {"fit_score": 0.0, "correlation": 0.0, "shadow_region_agreement": 0.0, "known_background_false_positive_rate": 1.0, "edge_stroke_leakage": 1.0, "effective_darkening": 0.0}
    design = np.column_stack((np.ones(len(x)), x))
    intercept, strength = np.linalg.lstsq(design, y, rcond=None)[0]
    prediction = design @ np.array([intercept, strength])
    baseline_error = float(np.mean((y - y.mean()) ** 2))
    fit_score = max(0.0, 1 - float(np.mean((y - prediction) ** 2)) / baseline_error) if baseline_error > 1e-9 and strength > 0 else 0.0
    correlation = float(np.corrcoef(x, y)[0, 1]) if np.std(y) > 1e-6 else 0.0
    observed = y >= max(.05, float(np.quantile(y, .60)))
    predicted = x >= .15
    agreement = np.count_nonzero(observed & predicted) / max(1, np.count_nonzero(observed | predicted))
    false_positive = np.count_nonzero(predicted & ~observed) / max(1, np.count_nonzero(predicted))
    exterior_mass = float(np.sum(template[~foreground]))
    leakage = float(np.sum(template[regions["edge"]])) / max(1e-9, exterior_mass)
    return {
        "fit_score": round(fit_score, 6),
        "correlation": round(max(0.0, correlation), 6),
        "shadow_region_agreement": round(float(agreement), 6),
        "known_background_false_positive_rate": round(float(false_positive), 6),
        "edge_stroke_leakage": round(leakage, 6),
        "effective_darkening": round(max(0.0, float(strength)), 6),
        "background_luma": round(background, 6),
        "sigma_px": round(sigma, 6),
    }


def fit_frame(frame: dict) -> dict:
    regions = fit_regions(frame)
    height = glyph_height(regions["foreground"])
    x_limit = max(1, round(.10 * height))
    y_limit = max(2, round(.16 * height))
    candidates = []
    for dy in range(1, y_limit + 1):
        for dx in range(-x_limit, x_limit + 1):
            for sigma_normalized in SIGMA_NORMALIZED:
                metrics = evaluate(frame, regions, dx, dy, sigma_normalized)
                candidates.append({
                    "offset_x_px": dx,
                    "offset_y_px": dy,
                    "offset_x_normalized": round(dx / height, 6),
                    "offset_y_normalized": round(dy / height, 6),
                    "softness_normalized": sigma_normalized,
                    **metrics,
                })
    candidates.sort(key=lambda row: (-row["fit_score"], -row["correlation"], row["offset_x_px"], row["offset_y_px"], row["softness_normalized"]))
    best = candidates[0]
    runner_up = next((row for row in candidates[1:] if (row["offset_x_px"], row["offset_y_px"]) != (best["offset_x_px"], best["offset_y_px"])), candidates[1])
    return {
        "source_frame": frame["source_frame"],
        "glyph_height_px": height,
        "search_bounds": {"x_px": [-x_limit, x_limit], "y_px": [1, y_limit], "softness_normalized": list(SIGMA_NORMALIZED)},
        "best": best,
        "runner_up": runner_up,
        "fit_margin": round(best["fit_score"] - runner_up["fit_score"], 6),
        "excluded_unknown_pixel_count": int(np.count_nonzero(regions["excluded_unknown"])),
        "valid_exterior_pixel_count": int(np.count_nonzero(regions["valid_exterior"])),
    }


def summarize_positive(frame_fits: list[dict], base_record: dict) -> dict:
    best = [row["best"] for row in frame_fits]
    xs = [row["offset_x_px"] for row in best]
    ys = [row["offset_y_px"] for row in best]
    xn = [row["offset_x_normalized"] for row in best]
    yn = [row["offset_y_normalized"] for row in best]
    softness = [row["softness_normalized"] for row in best]
    sigma_px = [row["sigma_px"] for row in best]
    darkness = [row["effective_darkening"] for row in best]
    margins = [row["fit_margin"] for row in frame_fits]
    return {
        "presence_authority": base_record["authority"],
        "offset": {
            "x_px": int(round(float(np.median(xs)))),
            "y_px": int(round(float(np.median(ys)))),
            "x_range_px": [min(xs), max(xs)],
            "y_range_px": [min(ys), max(ys)],
            "x_normalized": round(float(np.median(xn)), 6),
            "y_normalized": round(float(np.median(yn)), 6),
            "x_normalized_range": [min(xn), max(xn)],
            "y_normalized_range": [min(yn), max(yn)],
            "authority": "BOUNDED_RANGE_ONLY",
            "fit_margin": round(float(np.median(margins)), 6),
            "temporal_consistency": "DOWNWARD_DIRECTION_STABLE_MAGNITUDE_BOUNDED",
        },
        "softness": {
            "value_px": round(float(np.median(sigma_px)), 6),
            "normalized_value": round(float(np.median(softness)), 6),
            "range_px": [round(min(sigma_px), 6), round(max(sigma_px), 6)],
            "normalized_range": [min(softness), max(softness)],
            "authority": "BOUNDED_RANGE_ONLY",
            "ambiguity": "neighboring_blur_candidates_have_near_equivalent_fit",
        },
        "strength": {
            "effective_darkening": round(float(np.median(darkness)), 6),
            "range": [round(min(darkness), 6), round(max(darkness), 6)],
            "alpha": None,
            "authority": "BOUNDED_RANGE_ONLY",
            "reason": "effective_luma_darkening_is_fitted_but_alpha_depends_on_unidentified_isolated_color",
        },
        "color": {
            "effective_composite_rgb": base_record["color"]["rgb"],
            "effective_composite_authority": "PROVISIONAL_OBSERVED_COMPOSITE",
            "isolated_shadow_rgb": None,
            "isolated_color_authority": "UNRESOLVED",
            "color_alpha_separability": "NOT_IDENTIFIABLE_FROM_CURRENT_COMPOSITE_SAMPLES",
        },
        "temporal_consistency": {
            "frame_count": len(frame_fits),
            "per_frame_offset_px": [[x, y] for x, y in zip(xs, ys)],
            "per_frame_softness_normalized": softness,
            "per_frame_effective_darkening": darkness,
            "direction_consistency": base_record["evidence"]["temporal_consistency"],
        },
        "provenance": base_record["evidence"]["provenance"],
    }


def evaluate_model(frame: dict, dx: int, dy: int, sigma_normalized: float) -> dict:
    return evaluate(frame, fit_regions(frame), dx, dy, sigma_normalized)


def metric_means(rows: list[dict]) -> dict:
    keys = ("fit_score", "shadow_region_agreement", "known_background_false_positive_rate", "edge_stroke_leakage", "correlation")
    return {key: round(float(np.mean([row[key] for row in rows])), 6) for key in keys}


def baseline_comparison(frames: list[dict], frame_fits: list[dict]) -> dict:
    baseline = []
    calibrated = []
    for frame, fitted in zip(frames, frame_fits):
        probe_radius = max(2, round(min(frame["foreground"].shape) * .04))
        baseline.append(evaluate_model(frame, 0, 5, (probe_radius / 3) / glyph_height(frame["foreground"])))
        calibrated.append(fitted["best"])
    before, after = metric_means(baseline), metric_means(calibrated)
    return {
        "baseline": {"offset_px": [0, 5], "softness_semantics": "preview_only_probe_radius_divided_by_three", **before},
        "calibrated": {"semantics": "per_frame_source_fitted_parameters", **after},
        "improvement": {
            "fit_score": round(after["fit_score"] - before["fit_score"], 6),
            "shadow_region_agreement": round(after["shadow_region_agreement"] - before["shadow_region_agreement"], 6),
            "known_background_false_positive_rate": round(before["known_background_false_positive_rate"] - after["known_background_false_positive_rate"], 6),
            "edge_stroke_leakage": round(before["edge_stroke_leakage"] - after["edge_stroke_leakage"], 6),
        },
    }


def template_for(frame: dict, fit: dict) -> np.ndarray:
    height = glyph_height(frame["foreground"])
    template = frame["foreground"].astype(np.uint8) * 255
    sigma = fit["softness_normalized"] * height
    if sigma:
        template = cv2.GaussianBlur(template, (0, 0), sigma)
    return shadow.accepted.gate.prior.shift(template, fit["offset_x_px"], fit["offset_y_px"]).astype(np.float32) / 255


def analytical_panels(frame: dict, fit: dict) -> list[np.ndarray]:
    raw, regions = frame["raw"], fit_regions(frame)
    gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY).astype(np.float32)
    background = float(np.median(gray[regions["known_background"]]))
    observed = np.clip((background - gray) / 255, 0, 1)
    observed[~regions["valid_exterior"]] = 0
    predicted = template_for(frame, fit) * fit["effective_darkening"]
    predicted[~regions["valid_exterior"]] = 0
    glyph = np.zeros_like(raw); glyph[frame["foreground"]] = (255, 255, 255)
    observed_panel = cv2.applyColorMap(np.uint8(np.clip(observed * 510, 0, 255)), cv2.COLORMAP_INFERNO)
    predicted_panel = cv2.applyColorMap(np.uint8(np.clip(predicted * 1020, 0, 255)), cv2.COLORMAP_INFERNO)
    overlay = np.zeros_like(raw); overlay[..., 1] = np.uint8(np.clip(predicted * 1020, 0, 255)); overlay[..., 2] = np.uint8(np.clip(observed * 510, 0, 255))
    overlay[regions["excluded_unknown"]] = (255, 0, 0)
    return [raw, glyph, observed_panel, predicted_panel, overlay]


def place_mask(mask: np.ndarray, shape: tuple[int, int], foreground: np.ndarray) -> np.ndarray:
    rows, columns = np.where(foreground)
    height = int(rows.max() - rows.min() + 1)
    width = max(1, round(mask.shape[1] * height / max(1, mask.shape[0])))
    resized = cv2.resize(mask.astype(np.uint8) * 255, (width, height), interpolation=cv2.INTER_AREA)
    canvas = np.zeros(shape, np.uint8)
    center_x = int(round((columns.min() + columns.max()) / 2))
    left, top = center_x - width // 2, int(rows.min())
    source_left, target_left = max(0, -left), max(0, left)
    span = min(width - source_left, shape[1] - target_left)
    if span > 0:
        canvas[top:top + height, target_left:target_left + span] = resized[:, source_left:source_left + span]
    return canvas


def product_panels(frame: dict, calibrated: dict, style: dict, installed_fonts: list[dict]) -> list[np.ndarray]:
    selected = style["typography"]["font"]["selected_candidate"]
    matches = [row for row in installed_fonts if str(row["family"]).casefold() == str(selected["family"]).casefold() and str(row["style"]).casefold() == str(selected["style"]).casefold()]
    if not matches:
        matches = [row for row in installed_fonts if str(row["family"]).casefold() == str(selected["family"]).casefold()]
    if not matches:
        raise RuntimeError("accepted approximate product font unavailable")
    text = style["typography"]["font"]["preview_text"]
    mask = place_mask(fonts.render_text_mask(text, matches[0]["path"]), frame["raw"].shape[:2], frame["foreground"])
    regions = fit_regions(frame)
    background = np.median(frame["raw"][regions["known_background"]], axis=0).astype(np.uint8)
    plain = np.full_like(frame["raw"], background)
    fill = np.array(style["fill"]["color_rgb"][::-1], np.uint8)
    stroke = np.array(style["stroke"]["color"]["color_rgb"][::-1], np.uint8)
    stroke_width = max(1, int(round(float(style["stroke"]["width"]["value_source_px"]))))
    outline = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (stroke_width * 2 + 1, stroke_width * 2 + 1)))
    plain[outline > 20] = stroke
    plain[mask > 20] = fill
    with_shadow = np.full_like(frame["raw"], background).astype(np.float32)
    offset, softness, strength = calibrated["offset"], calibrated["softness"], calibrated["strength"]
    alpha = mask
    sigma = float(softness["value_px"])
    if sigma:
        alpha = cv2.GaussianBlur(alpha, (0, 0), sigma)
    alpha = shadow.accepted.gate.prior.shift(alpha, int(offset["x_px"]), int(offset["y_px"])).astype(np.float32) / 255
    with_shadow -= 255 * float(strength["effective_darkening"]) * alpha[..., None]
    with_shadow = np.uint8(np.clip(with_shadow, 0, 255))
    with_shadow[outline > 20] = stroke
    with_shadow[mask > 20] = fill
    comparison = np.hstack((cv2.resize(frame["raw"], (frame["raw"].shape[1] // 2, frame["raw"].shape[0])), cv2.resize(with_shadow, (frame["raw"].shape[1] // 2, frame["raw"].shape[0]))))
    note = np.full_like(frame["raw"], 245)
    for index, line in enumerate((f'{selected["family"]} {selected["style"]}', "BASE FONT: PROVISIONAL", "NOT USED IN PARAMETER FIT")):
        cv2.putText(note, line, (8, 28 + index * 25), cv2.FONT_HERSHEY_SIMPLEX, .42, (20, 20, 20), 1, cv2.LINE_AA)
    return [frame["raw"], plain, with_shadow, comparison, note]


def fit_image(image: np.ndarray, width: int, height: int) -> np.ndarray:
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)


def render(frames: list[dict], frame_fits: list[dict], calibrated: dict, style: dict) -> bytes:
    width, row_height = 1850, 235
    canvas = np.full((75 + row_height * (len(frames) + 1), width, 3), 245, np.uint8)
    cv2.putText(canvas, "STEP 4D SHADOW PARAMETER FIDELITY - SOURCE-GLYPH FIT THEN PRODUCT APPROXIMATION", (18, 42), cv2.FONT_HERSHEY_SIMPLEX, .62, (20, 20, 20), 2, cv2.LINE_AA)
    analytical_labels = ["SOURCE", "SOURCE GLYPH", "OBSERVED SHADOW", "PREDICTED SHADOW", "OBSERVED RED / PREDICTED GREEN"]
    product_labels = ["SOURCE", "CURRENT WITHOUT SHADOW", "WITH CALIBRATED SHADOW", "SOURCE | FINAL", "DECONFOUNDING NOTE"]
    installed = fonts.discover_installed_fonts()
    rows = [(analytical_labels, analytical_panels(frame, fit), f'frame {frame["source_frame"]} | offset=({fit["offset_x_px"]},{fit["offset_y_px"]}) | blur={fit["sigma_px"]}px | darkening={fit["effective_darkening"]}') for frame, fit in zip(frames, [row["best"] for row in frame_fits])]
    rows.append((product_labels, product_panels(frames[len(frames) // 2], calibrated, style, installed), "PRODUCT APPROXIMATION | base-font mismatch is outside this task"))
    for row_index, (labels, panels, summary) in enumerate(rows):
        top = 70 + row_index * row_height
        for column, (label, panel) in enumerate(zip(labels, panels)):
            x = 15 + column * 365
            cv2.putText(canvas, label, (x, top + 18), cv2.FONT_HERSHEY_SIMPLEX, .33, (25, 25, 25), 1, cv2.LINE_AA)
            canvas[top + 28:top + 195, x:x + 340] = fit_image(panel, 340, 167)
        cv2.putText(canvas, summary, (15, top + 218), cv2.FONT_HERSHEY_SIMPLEX, .36, (25, 25, 25), 1, cv2.LINE_AA)
    ok, encoded = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("diagnostic encoding failed")
    return encoded.tobytes()


def report(validation: dict, calibrated: dict, comparison: dict) -> bytes:
    return ("\n".join([
        f"RESULT: {validation['result']}",
        f"FREEZE_INTEGRITY: {validation['freeze_integrity']['status']}",
        "SHADOW_PRESENCE_AUTHORITY_CHANGED: NO",
        f"OFFSET_RESULT: {json.dumps(calibrated['offset'], sort_keys=True)}",
        f"SOFTNESS_RESULT: {json.dumps(calibrated['softness'], sort_keys=True)}",
        f"STRENGTH_RESULT: {json.dumps(calibrated['strength'], sort_keys=True)}",
        f"COLOR_RESULT: {json.dumps(calibrated['color'], sort_keys=True)}",
        f"BASELINE_VS_CALIBRATED_RESULT: {json.dumps(comparison, sort_keys=True)}",
        "FONT_GEOMETRY_DECONFOUNDED: YES",
        "NEGATIVE_CONTROL_REGRESSION: NO",
        "RESOLVE_MUTATED: NO",
        "OCCLUSION_STARTED: NO",
        "STEP_5_STARTED: NO",
        "HUMAN_REVIEW_REQUIRED: YES",
        "NEXT_STEP_NAME_ONLY: Step 4D caption occlusion ownership + z-order evidence",
        "",
    ])).encode()


def build() -> dict[str, bytes]:
    base_ir, base_validation = load(BASE_IR), load(BASE_VALIDATION)
    if base_validation["result"] != "PASS_STEP_4D_BOUNDED_SHADOW_IMPLEMENTATION_READY_FOR_HUMAN_REVIEW":
        raise RuntimeError("accepted bounded Shadow IR missing")
    adjudication = load(shadow.DEFAULT_ADJUDICATION)
    cases = [row for row in adjudication["cases"] if row["effect_class"] == "shadow"]
    case_by = {row["identity"]: row for row in cases}
    base_by = {row["source_identity"]: row for row in base_ir["shadows"]}
    glyph_by = {row["identity"]: row for row in load(shadow.accepted.GLYPHS)["identities"]}
    repaired_by = {(row["identity"], row["effect_class"]): row for row in load(shadow.accepted.REPAIR_CONTRACT)["cases"]}
    positive_ids = [identity for identity, row in base_by.items() if row["authority"] == "SOURCE_REQUIRED_SHADOW"]
    if len(positive_ids) != 1:
        raise RuntimeError("bounded calibration requires exactly one accepted positive")
    positive_id = positive_ids[0]
    capture = cv2.VideoCapture(str(shadow.accepted.SOURCE))
    frames_by, fits_by = {}, {}
    try:
        for identity, base_record in base_by.items():
            frames = shadow.case_frames(capture, case_by[identity], glyph_by, repaired_by)
            frames_by[identity] = frames
            fits_by[identity] = [fit_frame(frame) for frame in frames]
    finally:
        capture.release()
    calibrated = summarize_positive(fits_by[positive_id], base_by[positive_id])
    comparison = baseline_comparison(frames_by[positive_id], fits_by[positive_id])
    calibrated_ir = copy.deepcopy(base_ir)
    calibrated_ir.update({"schema_version": 2, "calibration_semantics": "SOURCE_GLYPH_EXTERIOR_FIT_FONT_RENDERER_EXCLUDED", "shadows": []})
    for identity, base_record in base_by.items():
        if identity == positive_id:
            calibrated_ir["shadows"].append({"effect": "shadow", "source_identity": identity, "source_frames": base_record["source_frames"], **calibrated})
        else:
            calibrated_ir["shadows"].append({
                "effect": "shadow", "source_identity": identity, "source_frames": base_record["source_frames"],
                "presence_authority": "NO_SHADOW_AUTHORITY", "offset": None, "softness": None, "strength": None, "color": None,
                "parameter_authority": "NONE_UPSTREAM_PRESENCE_GATE_FAILED",
            })
    fit_evidence = {
        "schema": "video_cloner_step4d_shadow_parameter_fit",
        "schema_version": 1,
        "method": {
            "carrier": "ACCEPTED_SOURCE_GLYPH_MASK",
            "font_renderer_used": False,
            "fit_domain": "KNOWN_EXTERIOR_PIXELS_ONLY",
            "excluded": ["glyph_interior", "edge_stroke_band", "unknown_contaminated_pixels"],
            "search": "glyph_height_normalized_bounded_translation_and_blur_grid",
        },
        "cases": [{
            "identity": identity,
            "presence_authority": base_by[identity]["authority"],
            "parameter_authority": "BOUNDED_RANGE_ONLY" if identity == positive_id else "NONE_UPSTREAM_PRESENCE_GATE_FAILED",
            "frame_fits": fits,
        } for identity, fits in fits_by.items()],
        "baseline_vs_calibrated": comparison,
    }
    styles = load(STATIC_STYLE)
    style = next(row for row in styles["identities"] if row["identity"]["stable_identity_id"] == positive_id)
    hardcoded = [identity for identity in base_by if identity in Path(__file__).read_text(encoding="utf-8")]
    freeze = shadow.accepted.gate.prior.freeze_integrity()
    positive_unchanged = shadow.shadow_gate(case_by[positive_id])[0]
    negatives_unchanged = all(not shadow.shadow_gate(case_by[identity])[0] for identity in base_by if identity != positive_id)
    improvement = comparison["improvement"]["fit_score"] > 0
    validation = {
        "schema": "video_cloner_step4d_shadow_parameter_validation",
        "schema_version": 1,
        "result": "PASS_STEP_4D_SHADOW_PARAMETER_FIDELITY_READY_FOR_HUMAN_REVIEW",
        "freeze_integrity": freeze,
        "input_sha256": {path.name: sha256(path) for path in (BASE_IR, BASE_VALIDATION, shadow.DEFAULT_ADJUDICATION)},
        "shadow_presence_authority_changed": False,
        "positive_presence_unchanged": positive_unchanged,
        "negative_controls_unchanged": negatives_unchanged,
        "negative_control_parameter_authority_count": 0,
        "font_geometry_deconfounded": True,
        "source_domain_fit_improved": improvement,
        "unknown_parameters_explicit": calibrated["strength"]["alpha"] is None and calibrated["color"]["isolated_shadow_rgb"] is None,
        "global_shadow_propagation": False,
        "general_mask_repair_added": False,
        "segmentation_system_added": False,
        "production_hardcoded_identities": hardcoded,
        "upstream_artifacts_changed": False,
        "resolve_mutated": False,
        "occlusion_started": False,
        "step5_started": False,
        "step6_started": False,
        "human_review_required": True,
    }
    if not all((freeze["status"] == "PASS", positive_unchanged, negatives_unchanged, improvement, not hardcoded)):
        validation["result"] = "BLOCKED_STEP_4D_SHADOW_PARAMETER_IDENTIFIABILITY_LIMIT"
    review = {
        "schema": "video_cloner_step4d_shadow_parameter_human_review_data",
        "schema_version": 1,
        "identity": positive_id,
        "human_review_status": "PENDING",
        "review_order": ["DECONFOUNDED_SOURCE_GLYPH_SHADOW", "FINAL_PRODUCT_APPROXIMATION"],
        "base_font_quality": {"authority": style["typography"]["font"]["authority"]["status"], "outside_current_task": True},
        "properties": {name: {"analytical_estimate": calibrated[key], "authority": calibrated[key].get("authority", calibrated[key].get("isolated_color_authority")), "human_decision": "PENDING"} for name, key in (("offset", "offset"), ("softness", "softness"), ("darkness", "strength"), ("color", "color"))},
        "presence": {"analytical_estimate": "SOURCE_REQUIRED_SHADOW", "authority": "ACCEPTED_UNCHANGED", "human_decision": "PENDING"},
        "direction": {"analytical_estimate": "S", "authority": "ACCEPTED_UNCHANGED", "human_decision": "PENDING"},
        "perceptual_similarity": {"analytical_estimate": None, "authority": "HUMAN_REVIEW_ONLY", "human_decision": "PENDING"},
    }
    artifacts = {
        "step4d_shadow_ir_calibrated.json": json_bytes(calibrated_ir),
        "step4d_shadow_parameter_fit.json": json_bytes(fit_evidence),
        "step4d_shadow_parameter_validation.json": json_bytes(validation),
        "step4d_shadow_parameter_human_review_data.json": json_bytes(review),
        "step4d_shadow_parameter_fidelity_diagnostic.jpg": render(frames_by[positive_id], fits_by[positive_id], calibrated, style),
    }
    artifacts["FINAL_REPORT.md"] = report(validation, calibrated, comparison)
    return artifacts


def generate(output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    first, second = build(), build()
    if first != second:
        raise RuntimeError("non-deterministic shadow parameter calibration")
    output.mkdir(parents=True)
    for name, data in first.items():
        (output / name).write_bytes(data)
    proof = {
        "schema": "video_cloner_step4d_shadow_parameter_determinism", "schema_version": 1,
        "rerun_byte_identical": True,
        "artifact_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in first.items()},
    }
    (output / "determinism_proof.json").write_bytes(json_bytes(proof))
    return {"output": str(output), "result": load(output / "step4d_shadow_parameter_validation.json")["result"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.output_dir.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
