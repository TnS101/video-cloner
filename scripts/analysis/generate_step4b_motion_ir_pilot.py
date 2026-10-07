#!/usr/bin/env python3
"""Generate a bounded, editor-neutral multi-property boundary Motion IR pilot."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.davinci.redetect_caption_lifecycle_step_3D import expand_bbox, multi_scale_match

STATIC_FREEZE = ROOT / ".agent/state/video_cloner_static_caption_freeze.json"
TIMING_FREEZE = ROOT / ".agent/state/video_cloner_timing_persistence_freeze.json"
STATIC_CONTRACT = ROOT / ".agent/reports/VIDEO_CLONER_STEP2F_FONT_AUTHORITY_CALIBRATION_20260927/20260927T020000000Z_calibrated/whole_reel_static_style_contract_calibrated.json"
GLYPH_EVIDENCE = ROOT / ".agent/reports/VIDEO_CLONER_STEP2B1_FINAL_MULTI_OBJECT_MASK_ISOLATION_REPAIR_20260927/20260927T000000000Z_bounded/reel2_glyph_evidence_v2_mask_isolation_corrected.json"
SOURCE_VIDEO = ROOT / "input/DcJRJtUKScu.mp4"
TIMELINE_FPS = 24.0
SCALES = (0.55, 0.7, 0.82, 0.9, 0.96, 1.0, 1.04, 1.1, 1.18, 1.3, 1.45)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def decode(shape: list[int], runs: list[list[int]]) -> np.ndarray:
    flat = np.zeros(int(shape[0]) * int(shape[1]), dtype=np.uint8)
    for start, length in runs:
        flat[int(start):int(start) + int(length)] = 1
    return flat.reshape(int(shape[0]), int(shape[1]))


def signs(values: list[float]) -> list[int]:
    if not values:
        return []
    epsilon = max(0.0005, max(abs(value) for value in values) * 0.15)
    return [1 if value > epsilon else -1 if value < -epsilon else 0 for value in values]


def sign_changes(values: list[float]) -> int:
    nonzero = [value for value in signs(values) if value]
    return sum(left != right for left, right in zip(nonzero, nonzero[1:]))


def derive_features(samples: list[dict]) -> dict:
    if len(samples) < 2:
        return {"velocity": [], "acceleration": [], "direction_changes": 0, "overshoot": False, "oscillation": False, "hold_intervals": [], "settling": False}
    velocity = []
    for left, right in zip(samples, samples[1:]):
        dx = right["position"]["x"] - left["position"]["x"]
        dy = right["position"]["y"] - left["position"]["y"]
        velocity.append({"frame": right["frame"], "x": round(dx, 8), "y": round(dy, 8), "speed": round(math.hypot(dx, dy), 8)})
    acceleration = [round(right["speed"] - left["speed"], 8) for left, right in zip(velocity, velocity[1:])]
    changes = sign_changes([row["x"] for row in velocity]) + sign_changes([row["y"] for row in velocity])
    max_speed = max(row["speed"] for row in velocity)
    hold_threshold = max(0.00075, max_speed * 0.18)
    holds = [[row["frame"] - 1, row["frame"] + 1] for row in velocity if row["speed"] <= hold_threshold]
    scales = [row["scale"]["value"] for row in samples if row.get("scale")]
    overshoot = bool(scales and max(scales) > 1.08 and scales.index(max(scales)) < len(scales) - 1 and abs(scales[-1] - 1.0) < abs(max(scales) - 1.0))
    settling = bool(scales and len(scales) >= 3 and abs(scales[-1] - 1.0) < abs(scales[-2] - 1.0))
    return {
        "velocity": velocity,
        "acceleration": acceleration,
        "direction_changes": changes,
        "overshoot": overshoot,
        "oscillation": changes >= 2,
        "hold_intervals": holds,
        "settling": settling,
    }


def scale_gate(glyph: dict, observations: list[dict], tracked: dict[int, float], seed_area: float) -> dict:
    usable = []
    for row in observations:
        frame = round(float(row["timestamp"]) * TIMELINE_FPS)
        if frame not in tracked:
            continue
        x1, y1, x2, y2 = row["bbox"]
        width, height = x2 - x1, y2 - y1
        if width <= 0 or height <= 0:
            continue
        usable.append((tracked[frame], math.sqrt(width * height) / max(1.0, math.sqrt(seed_area)), width / height, float(row.get("background_contamination") or 0.0)))
    if len(usable) < 3 or float(glyph.get("mask_confidence") or 0.0) < 0.4:
        return {"supported": False, "reason": "insufficient_scale_corroboration"}
    template = np.asarray([row[0] for row in usable])
    extent = np.asarray([row[1] for row in usable])
    aspect = np.asarray([row[2] for row in usable])
    correlation = float(np.corrcoef(template, extent)[0, 1]) if np.std(template) > 1e-6 and np.std(extent) > 1e-6 else 0.0
    median_error = float(np.median(np.abs(template - extent)))
    aspect_cv = float(np.std(aspect) / max(1e-6, np.mean(aspect)))
    contamination = float(np.median([row[3] for row in usable]))
    supported = correlation >= 0.55 and median_error <= 0.22 and aspect_cv <= 0.15 and contamination <= 0.2
    return {"supported": supported, "reason": None if supported else "template_mask_geometry_disagree", "correlation": round(correlation, 6), "median_error": round(median_error, 6), "aspect_cv": round(aspect_cv, 6), "median_contamination": round(contamination, 6)}


def visibility_strength(frame: np.ndarray, bbox: tuple[int, int, int, int], mask: np.ndarray) -> float:
    x1, y1, x2, y2 = bbox
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return 0.0
    resized = cv2.resize(mask, (crop.shape[1], crop.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)
    if not resized.any():
        return 0.0
    pad = max(3, round(min(crop.shape[:2]) * 0.08))
    outer = frame[max(0, y1 - pad):min(frame.shape[0], y2 + pad), max(0, x1 - pad):min(frame.shape[1], x2 + pad)]
    if outer.size == 0:
        return 0.0
    border = np.concatenate((outer[:pad].reshape(-1, 3), outer[-pad:].reshape(-1, 3), outer[:, :pad].reshape(-1, 3), outer[:, -pad:].reshape(-1, 3)))
    background = np.median(border.astype(np.float32), axis=0)
    distances = np.linalg.norm(crop.astype(np.float32) - background, axis=2)
    return float(np.percentile(distances[resized], 65))


def track_case(case: dict, glyph: dict, capture: cv2.VideoCapture, source_fps: float, frame_width: int, frame_height: int) -> dict:
    observations = [row for row in glyph.get("observations", []) if row.get("accepted") and row.get("bbox")]
    if not observations:
        return {"control_id": case["control_id"], "identity": case.get("identity"), "boundary": case["boundary"], "status": "UNRESOLVED", "reason": "no_accepted_seed_observation", "samples": [], "features": derive_features([]), "rotation": None}
    start, end = map(int, case["analysis_interval"])
    stable_target = end if case["boundary"] == "entry" else start
    seed = min(observations, key=lambda row: (abs(round(float(row["timestamp"]) * TIMELINE_FPS) - stable_target), -float(row.get("foreground_confidence") or 0.0)))
    seed_bbox = tuple(map(int, seed["bbox"]))
    capture.set(cv2.CAP_PROP_POS_FRAMES, int(seed["source_frame"]))
    ok, seed_frame = capture.read()
    if not ok:
        raise RuntimeError("seed frame unavailable")
    x1, y1, x2, y2 = seed_bbox
    template = seed_frame[y1:y2, x1:x2]
    all_boxes = [row["bbox"] for row in observations]
    union = (min(row[0] for row in all_boxes), min(row[1] for row in all_boxes), max(row[2] for row in all_boxes), max(row[3] for row in all_boxes))
    search_bbox = expand_bbox(union, frame_width, frame_height, 2.2, 2.2)
    sx1, sy1, sx2, sy2 = search_bbox
    mask = decode(seed["estimated_mask_shape"], seed.get("estimated_mask_rle") or [])
    mask_ok = bool(float(glyph.get("mask_confidence") or 0.0) >= 0.25 and float(glyph.get("unknown_ratio") or 1.0) <= 0.5 and float(seed.get("background_contamination") or 1.0) <= 0.3 and mask.any())
    stable_strength = visibility_strength(seed_frame, seed_bbox, mask) if mask_ok else 0.0
    visibility_ok = mask_ok and stable_strength >= 8.0
    tracked_scales: dict[int, float] = {}
    raw = []
    for timeline_frame in range(start, end + 1):
        source_frame = max(0, round(timeline_frame * source_fps / TIMELINE_FPS))
        capture.set(cv2.CAP_PROP_POS_FRAMES, source_frame)
        ok, frame = capture.read()
        if not ok:
            continue
        match = multi_scale_match(frame[sy1:sy2, sx1:sx2], template, SCALES)
        mx, my = match["location"]
        mw, mh = match["size"]
        bbox = (sx1 + mx, sy1 + my, sx1 + mx + mw, sy1 + my + mh)
        tracked_scales[timeline_frame] = float(match["scale"])
        visibility = visibility_strength(frame, bbox, mask) / stable_strength if visibility_ok else None
        raw.append({"frame": timeline_frame, "source_frame": source_frame, "position": {"x": round((bbox[0] + bbox[2]) / (2 * frame_width), 8), "y": round((bbox[1] + bbox[3]) / (2 * frame_height), 8), "authority": "SOURCE_TEMPLATE_TRACK"}, "template_scale": round(float(match["scale"]), 6), "match_score": round(float(match["score"]), 6), "relative_visibility": {"value": round(max(0.0, min(1.5, visibility)), 6), "authority": "SOURCE_MASK_RELATIVE_STRENGTH"} if visibility is not None else None, "rotation": None})
    seed_area = max(1, (x2 - x1) * (y2 - y1))
    scale = scale_gate(glyph, observations, tracked_scales, seed_area)
    samples = []
    for row in raw:
        samples.append({**row, "scale": {"value": row.pop("template_scale"), "authority": "CORROBORATED_TEMPLATE_MASK_GEOMETRY"} if scale["supported"] else None})
    features = derive_features(samples)
    has_position = len(samples) >= 2
    has_visibility = sum(row["relative_visibility"] is not None for row in samples) >= 2
    has_scale = scale["supported"]
    if features["oscillation"]:
        label = "CUSTOM_OSCILLATION"
    elif has_scale and features["overshoot"]:
        label = "SCALE_OVERSHOOT"
    elif has_position and has_visibility:
        label = "FADE_SLIDE"
    elif has_position:
        label = "SLIDE"
    elif has_visibility:
        label = "FADE"
    else:
        label = None
    return {"control_id": case["control_id"], "identity": case.get("identity"), "boundary": case["boundary"], "interval": [start, end + 1], "samples": samples, "features": features, "derived_label": label, "authority": "PILOT_SOURCE_MEASURED", "channel_authority": {"position": "SOURCE_TEMPLATE_TRACK" if has_position else "UNRESOLVED", "scale": "CORROBORATED_TEMPLATE_MASK_GEOMETRY" if has_scale else "UNRESOLVED", "relative_visibility": "SOURCE_MASK_RELATIVE_STRENGTH" if has_visibility else "UNRESOLVED", "rotation": "UNSUPPORTED"}, "scale_gate": scale, "provenance": ["source_video", "frozen_glyph_evidence", "frozen_step4a_interval_reference"]}


def evaluate(case: dict, result: dict) -> dict:
    if case.get("expect_no_fabricated_motion"):
        passed = result.get("status") == "UNRESOLVED" and not result.get("samples")
        return {"match": "YES" if passed else "NO", "checks": {"no_fabricated_motion": passed}}
    channels = result["channel_authority"]
    checks = {}
    for channel in case.get("required_channels", []):
        checks[f"channel_{channel}"] = channels.get(channel) not in {None, "UNRESOLVED", "UNSUPPORTED"}
    for channel in case.get("forbidden_channels", []):
        checks[f"reject_{channel}"] = channels.get(channel) in {None, "UNRESOLVED", "UNSUPPORTED"}
    for feature in case.get("required_features", []):
        value = result["features"].get(feature)
        checks[f"feature_{feature}"] = bool(value)
    for feature in case.get("forbidden_features", []):
        checks[f"reject_feature_{feature}"] = not bool(result["features"].get(feature))
    axis = case.get("dominant_axis")
    if axis and len(result["samples"]) >= 2:
        first, last = result["samples"][0]["position"], result["samples"][-1]["position"]
        checks[f"axis_{axis}"] = abs(last[axis] - first[axis]) >= abs(last["y" if axis == "x" else "x"] - first["y" if axis == "x" else "x"])
    failed = sum(not value for value in checks.values())
    return {"match": "YES" if not failed else "PARTIAL" if failed < len(checks) else "NO", "checks": checks}


def pair_results(results: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in results:
        identity = row.get("identity")
        if identity:
            grouped.setdefault(identity, []).append(row)
    pairs = []
    for identity, rows in grouped.items():
        entry = next((row for row in rows if row.get("boundary") == "entry" and row.get("samples")), None)
        exit_row = next((row for row in rows if row.get("boundary") == "exit" and row.get("samples")), None)
        if not entry or not exit_row:
            continue
        def displacement(row: dict) -> tuple[float, float]:
            first, last = row["samples"][0]["position"], row["samples"][-1]["position"]
            return last["x"] - first["x"], last["y"] - first["y"]
        a, b = displacement(entry), displacement(exit_row)
        dot = a[0] * b[0] + a[1] * b[1]
        entry_peak = max((row["speed"] for row in entry["features"]["velocity"]), default=0.0)
        exit_peak = max((row["speed"] for row in exit_row["features"]["velocity"]), default=0.0)
        speed_ratio = max(entry_peak, exit_peak) / max(1e-9, min(entry_peak, exit_peak))
        state = "REVERSED" if dot < 0 and len(entry["samples"]) == len(exit_row["samples"]) and speed_ratio <= 1.25 else "ASYMMETRIC" if set(entry["channel_authority"]) == set(exit_row["channel_authority"]) else "INDEPENDENT"
        pairs.append({"identity": identity, "entry_control": entry["control_id"], "exit_control": exit_row["control_id"], "relationship": state})
    return pairs


def verify_freezes() -> dict:
    static, timing = load(STATIC_FREEZE), load(TIMING_FREEZE)
    if static.get("result") != "PASS_STEP_3_HUMAN_ACCEPTED_STATIC_CAPTIONS_FROZEN" or timing.get("result") != "PASS_STEP_4A_HUMAN_ACCEPTED_TIMING_PERSISTENCE_FROZEN":
        raise RuntimeError("accepted freeze missing")
    for group in (static["frozen_static_authority"], timing["frozen_timing_authority"]):
        for item in group.values():
            if isinstance(item, dict) and item.get("path") and sha256(ROOT / item["path"]) != item["sha256"]:
                raise RuntimeError(f"freeze drift: {item['path']}")
    return {"static_freeze_sha256": sha256(STATIC_FREEZE), "timing_freeze_sha256": sha256(TIMING_FREEZE)}


def render_diagnostic(cases: list[dict], results: list[dict], source: Path) -> bytes:
    by_id = {row["control_id"]: row for row in results}
    width, row_height = 1400, 250
    image = np.full((70 + len(cases) * row_height, width, 3), 245, np.uint8)
    cv2.putText(image, "STEP 4B MULTI-PROPERTY MOTION IR PILOT", (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 20), 2, cv2.LINE_AA)
    capture = cv2.VideoCapture(str(source)); source_fps = capture.get(cv2.CAP_PROP_FPS)
    colors = {"x": (220, 70, 40), "y": (40, 140, 40), "visibility": (30, 30, 210), "scale": (160, 60, 160)}
    for index, case in enumerate(cases):
        top = 70 + index * row_height; row = by_id[case["control_id"]]; result = row["evaluation"]
        cv2.putText(image, f'{case["control_id"]} {case["human_expectation"]} | {result["match"]} | {row.get("derived_label")}', (16, top + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (20, 20, 20), 1, cv2.LINE_AA)
        frames = list(range(case["analysis_interval"][0], case["analysis_interval"][1] + 1))
        picks = sorted(set([frames[0], frames[len(frames)//2], frames[-1]]))
        for col, frame_no in enumerate(picks):
            capture.set(cv2.CAP_PROP_POS_FRAMES, round(frame_no * source_fps / TIMELINE_FPS)); ok, frame = capture.read()
            if ok:
                thumb = cv2.resize(frame, (90, 160), interpolation=cv2.INTER_AREA); x = 16 + col * 125; image[top+40:top+200, x:x+90] = thumb
                cv2.putText(image, f"F{frame_no}", (x, top+218), cv2.FONT_HERSHEY_SIMPLEX, .35, (30,30,30), 1, cv2.LINE_AA)
        samples = row.get("samples") or []
        chart_x, chart_y, chart_w, chart_h = 410, top + 40, 950, 160
        cv2.rectangle(image, (chart_x, chart_y), (chart_x+chart_w, chart_y+chart_h), (180,180,180), 1)
        series = {"x": [s["position"]["x"] for s in samples], "y": [s["position"]["y"] for s in samples], "visibility": [s["relative_visibility"]["value"] if s.get("relative_visibility") else None for s in samples], "scale": [s["scale"]["value"] if s.get("scale") else None for s in samples]}
        for series_index, (name, values) in enumerate(series.items()):
            usable = [(i, value) for i, value in enumerate(values) if value is not None]
            if len(usable) < 2: continue
            raw = [value for _, value in usable]; lo, hi = min(raw), max(raw); span = max(1e-6, hi-lo)
            points = [(chart_x + round(i * chart_w / max(1, len(samples)-1)), chart_y + series_index*38 + 30 - round((value-lo)/span*26)) for i, value in usable]
            cv2.polylines(image, [np.asarray(points, np.int32)], False, colors[name], 2, cv2.LINE_AA); cv2.putText(image, name, (chart_x+5, chart_y+series_index*38+15), cv2.FONT_HERSHEY_SIMPLEX, .34, colors[name], 1, cv2.LINE_AA)
        cv2.putText(image, json.dumps(row.get("features", {}), sort_keys=True)[:145], (410, top+225), cv2.FONT_HERSHEY_SIMPLEX, .3, (50,50,50), 1, cv2.LINE_AA)
    capture.release(); ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok: raise RuntimeError("diagnostic encoding failed")
    return encoded.tobytes()


def build(controls: Path) -> dict[str, bytes]:
    freeze = verify_freezes(); fixture = load(controls); static = load(STATIC_CONTRACT); glyph = load(GLYPH_EVIDENCE)
    glyph_by = {row["identity"]: row for row in glyph["identities"]}; frozen_ids = {row["identity"]["stable_identity_id"] for row in static["identities"]}
    capture = cv2.VideoCapture(str(SOURCE_VIDEO)); source_fps = float(capture.get(cv2.CAP_PROP_FPS)); width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)); height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    results = []
    for case in fixture["controls"]:
        identity = case.get("identity")
        if not identity or identity not in glyph_by:
            row = {"control_id": case["control_id"], "identity": identity, "boundary": case["boundary"], "status": "UNRESOLVED", "reason": "identity_unavailable", "samples": [], "features": derive_features([]), "rotation": None}
        else:
            row = track_case(case, glyph_by[identity], capture, source_fps, width, height)
        row["human_expectation"] = case["human_expectation"]; row["evaluation"] = evaluate(case, row); results.append(row)
    capture.release()
    pairs = pair_results(results); counts = {name: sum(row["evaluation"]["match"] == name for row in results) for name in ("YES", "PARTIAL", "NO")}
    production = Path(__file__).read_text(encoding="utf-8")
    hardcoding = sorted(set(re.findall(r"\b(?:F\d+|caption_tracklet_\d+|continuous_visual_identity_\d+)\b", production)))
    passed = counts["NO"] == 0 and counts["YES"] >= len(results) // 2 + 1 and counts["YES"] + counts["PARTIAL"] == len(results) and not hardcoding
    ir = {"schema": "video_cloner_step4b_boundary_motion_ir_pilot", "schema_version": 1, "result": "PASS_STEP_4B_BOUNDARY_LOCAL_MOTION_IR_PILOT_READY_FOR_HUMAN_REVIEW" if passed else "FAIL_STEP_4B_BOUNDARY_LOCAL_MOTION_IR_PILOT", "scope": "BOUNDED_HUMAN_CONTROLS_ONLY_NOT_WHOLE_REEL_AUTHORITY", "controls": results, "entry_exit_pairs": pairs}
    validation = {"schema": "video_cloner_step4b_motion_ir_pilot_validation", "schema_version": 1, "ok": passed, "control_match_counts": counts, "production_hardcoding": hardcoding, "freeze_integrity": freeze, "identity_graph_count": len(frozen_ids), "step4c_started": False, "resolve_mutated": False}
    diagnostic_data = {"schema": "video_cloner_step4b_motion_ir_pilot_diagnostic", "schema_version": 1, "controls": [{"control_id": row["control_id"], "human_expectation": row["human_expectation"], "machine_result": row.get("derived_label"), "features": row["features"], "evaluation": row["evaluation"]} for row in results]}
    artifacts = {"step4b_motion_ir_pilot.json": json_bytes(ir), "step4b_motion_ir_pilot_validation.json": json_bytes(validation), "step4b_motion_ir_pilot_diagnostic.json": json_bytes(diagnostic_data), "step4b_motion_ir_pilot_diagnostic.jpg": render_diagnostic(fixture["controls"], results, SOURCE_VIDEO)}
    return artifacts


def generate(controls: Path, output: Path) -> dict:
    if output.exists(): raise FileExistsError(output)
    first, second = build(controls), build(controls); identical = first == second
    output.mkdir(parents=True)
    for name, data in first.items(): (output / name).write_bytes(data)
    proof = {"schema": "video_cloner_step4b_motion_ir_pilot_determinism", "schema_version": 1, "rerun_byte_identical": identical, "artifact_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in first.items()}}
    (output / "determinism_proof.json").write_bytes(json_bytes(proof))
    if not identical: raise RuntimeError("pilot is not deterministic")
    return {"output": str(output), "result": load(output / "step4b_motion_ir_pilot.json")["result"]}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--controls", required=True, type=Path); parser.add_argument("--output-dir", required=True, type=Path); args = parser.parse_args()
    print(json.dumps(generate(args.controls.resolve(), args.output_dir.resolve()), sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
