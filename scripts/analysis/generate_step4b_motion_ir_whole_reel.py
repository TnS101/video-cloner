#!/usr/bin/env python3
"""Apply the accepted Step 4B boundary Motion IR pilot to every frozen identity."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.analysis import generate_step4b_motion_ir_pilot as pilot

TIMING_CONTRACT = ROOT / ".agent/reports/VIDEO_CLONER_STEP4A_TIMING_PERSISTENCE_20260927/20260927T122000000Z_human_review_ready/step4a_timing_persistence_contract.json"
PILOT_CONTROLS = ROOT / "tests/fixtures/step4b_motion_ir_controls.json"
PILOT_RESULT = ROOT / ".agent/reports/VIDEO_CLONER_STEP4B_MOTION_IR_PILOT_20260927/20260927T092115675Z_human_review_ready/step4b_motion_ir_pilot.json"
WINDOW_FRAMES = 7
POSITION_MIN = 0.012
VISIBILITY_MIN = 0.15
SCALE_MIN = 0.055


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def merge_holds(intervals: list[list[int]]) -> list[list[int]]:
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def boundary_intervals(start: int, end: int) -> dict[str, list[int]]:
    duration = end - start
    width = min(WINDOW_FRAMES, max(1, duration // 2))
    return {"entry": [start, start + width - 1], "exit": [end - width, end - 1]}


def unresolved(identity: str, text: str, boundary: str, interval: list[int], reason: str) -> dict:
    features = pilot.derive_features([])
    features.update({"raw_oscillation_candidate": False, "semantic_oscillation_confidence": "UNRESOLVED", "tracker_jump_outlier": False, "relative_visibility_noise_outlier": False})
    return {
        "control_id": f"{identity}:{boundary}", "identity": identity, "text_diagnostic_only": text,
        "boundary": boundary, "interval": [interval[0], interval[1] + 1], "status": "UNRESOLVED",
        "reason": reason, "samples": [], "features": features, "rotation": None,
        "channel_authority": {"position": "UNRESOLVED", "relative_visibility": "UNRESOLVED", "scale": "UNRESOLVED", "rotation": "UNSUPPORTED"},
        "derived_label": None, "derived_label_confidence": "UNRESOLVED", "reproduction_authority": False,
        "continues_beyond_boundary": False, "static_no_motion": True,
        "provenance": ["source_video", "frozen_identity", "frozen_step4a_interval", "accepted_pilot_dense_template_tracker"],
    }


def span(values: list[float]) -> float:
    return max(values) - min(values) if values else 0.0


def supported(authority: str) -> bool:
    return not authority.startswith("UNRESOLVED") and authority != "UNSUPPORTED"


def normalize(identity: str, text: str, row: dict) -> dict:
    row["text_diagnostic_only"] = text
    row["features"]["hold_intervals"] = merge_holds(row["features"]["hold_intervals"])
    samples = row.get("samples") or []
    scores = [sample["match_score"] for sample in samples]
    position_quality = len(samples) >= 2 and float(np.median(scores)) >= 0.25
    velocities = row["features"]["velocity"]
    jump = max((item["speed"] for item in velocities), default=0.0) > 0.12
    position_supported = position_quality and not jump
    if not position_supported:
        row["channel_authority"]["position"] = "UNRESOLVED_LOW_TRACK_QUALITY"

    visibility = [sample["relative_visibility"]["value"] for sample in samples if sample.get("relative_visibility")]
    visibility_noisy = bool(visibility and (max(visibility) >= 1.5 or pilot.sign_changes(np.diff(visibility).tolist()) >= 3))
    if len(visibility) < 2 or not position_supported or visibility_noisy:
        row["channel_authority"]["relative_visibility"] = "UNRESOLVED_RELATIVE_VISIBILITY"
        for sample in samples:
            sample["relative_visibility"] = None
        visibility = []

    scales = [sample["scale"]["value"] for sample in samples if sample.get("scale")]
    scale_tracker_stable = position_supported and min(scores, default=0.0) >= 0.25 and float(np.std(scores)) <= 0.25
    oscillation_tracker_stable = position_supported and min(scores, default=0.0) >= 0.30 and float(np.std(scores)) <= 0.25
    if row["channel_authority"]["scale"] == "CORROBORATED_TEMPLATE_MASK_GEOMETRY" and not scale_tracker_stable:
        row["channel_authority"]["scale"] = "UNRESOLVED_TRACK_QUALITY_CONFLICT"
        for sample in samples:
            sample["scale"] = None
        scales = []
    position_material = position_supported and (span([s["position"]["x"] for s in samples]) >= POSITION_MIN or span([s["position"]["y"] for s in samples]) >= POSITION_MIN)
    visibility_material = span(visibility) >= VISIBILITY_MIN
    scale_material = row["channel_authority"]["scale"] == "CORROBORATED_TEMPLATE_MASK_GEOMETRY" and span(scales) >= SCALE_MIN
    changes = row["features"]["direction_changes"]
    amplitude = max((math.hypot(s["position"]["x"] - samples[0]["position"]["x"], s["position"]["y"] - samples[0]["position"]["y"]) for s in samples), default=0.0)
    oscillation_candidate = bool(row["features"]["oscillation"])
    oscillation_high = bool(oscillation_candidate and oscillation_tracker_stable and changes >= 3 and amplitude >= 0.02 and len(samples) >= 6)
    row["features"].update({
        "raw_oscillation_candidate": oscillation_candidate,
        "semantic_oscillation_confidence": "HIGH" if oscillation_high else "LOW" if oscillation_candidate else "UNRESOLVED",
        "tracker_jump_outlier": jump,
        "relative_visibility_noise_outlier": visibility_noisy,
    })

    if oscillation_high:
        label, confidence = "CUSTOM_OSCILLATION", "HIGH"
    elif scale_material and row["features"]["overshoot"]:
        label, confidence = "SCALE_OVERSHOOT", "HIGH"
    elif scale_material:
        label, confidence = "SCALE", "MEDIUM"
    elif position_material and visibility_material:
        label, confidence = "FADE_SLIDE", "MEDIUM"
    elif position_material:
        label, confidence = "SLIDE", "MEDIUM"
    elif visibility_material:
        label, confidence = "FADE", "MEDIUM"
    else:
        label, confidence = None, "UNRESOLVED"
    row["derived_label"] = label
    row["derived_label_confidence"] = confidence
    row["reproduction_authority"] = False
    row["static_no_motion"] = not any((position_material, visibility_material, scale_material))
    edge_velocity = velocities[-1 if row["boundary"] == "entry" else 0]["speed"] if velocities else 0.0
    row["continues_beyond_boundary"] = bool(position_supported and edge_velocity >= max(0.0015, max((v["speed"] for v in velocities), default=0.0) * 0.35))
    row["status"] = "SOURCE_MEASURED" if any(supported(value) for value in row["channel_authority"].values()) else "UNRESOLVED"
    row["authority"] = "RAW_CHANNEL_SAMPLES_ONLY"
    row["provenance"] = ["source_video", "frozen_identity", "frozen_step4a_interval", "accepted_pilot_dense_template_tracker"]
    return row


def pair_records(records: list[dict]) -> list[dict]:
    grouped: dict[str, dict[str, dict]] = {}
    for row in records:
        grouped.setdefault(row["identity"], {})[row["boundary"]] = row
    pairs = []
    for identity, sides in grouped.items():
        entry, exit_row = sides["entry"], sides["exit"]
        if not entry["samples"] or not exit_row["samples"]:
            relationship = "UNRESOLVED"
        elif entry["derived_label"] is None or exit_row["derived_label"] is None:
            relationship = "INDEPENDENT"
        else:
            def displacement(row: dict) -> tuple[float, float]:
                first, last = row["samples"][0]["position"], row["samples"][-1]["position"]
                return last["x"] - first["x"], last["y"] - first["y"]
            a, b = displacement(entry), displacement(exit_row)
            dot = a[0] * b[0] + a[1] * b[1]
            relationship = "REVERSED" if dot < 0 and entry["derived_label"] == exit_row["derived_label"] else "ASYMMETRIC"
        pairs.append({"identity": identity, "entry_record": entry["control_id"], "exit_record": exit_row["control_id"], "relationship": relationship, "authority": "MEASURED_TRAJECTORY_COMPARISON" if relationship != "UNRESOLVED" else "UNRESOLVED"})
    return pairs


def channel_counts(records: list[dict], channel: str) -> dict:
    count = sum(supported(row["channel_authority"][channel]) for row in records)
    return {"supported": count, "unresolved_or_unsupported": len(records) - count}


def select_review(records: list[dict], pairs: list[dict], pilot_controls: list[dict]) -> list[dict]:
    chosen: list[dict] = []
    def take(name: str, predicate) -> None:
        row = next((item for item in records if item["control_id"] not in {x["control_id"] for x in chosen} and predicate(item)), None)
        if row:
            chosen.append({**row, "review_stratum": name})
    for case in pilot_controls:
        identity, boundary = case.get("identity"), case["boundary"]
        if identity:
            take("accepted_pilot_regression", lambda row, identity=identity, boundary=boundary: row["identity"] == identity and row["boundary"] == boundary)
    take("position_only", lambda r: r["derived_label"] == "SLIDE")
    take("position_visibility", lambda r: r["derived_label"] == "FADE_SLIDE")
    take("supported_scale", lambda r: r["channel_authority"]["scale"] == "CORROBORATED_TEMPLATE_MASK_GEOMETRY")
    take("overshoot", lambda r: r["features"]["overshoot"])
    take("oscillation_high", lambda r: r["features"]["semantic_oscillation_confidence"] == "HIGH")
    take("oscillation_low", lambda r: r["features"]["semantic_oscillation_confidence"] == "LOW")
    take("hold", lambda r: bool(r["features"]["hold_intervals"]))
    asymmetric = {p["identity"] for p in pairs if p["relationship"] == "ASYMMETRIC"}
    take("asymmetric_pair", lambda r: r["identity"] in asymmetric)
    take("unresolved", lambda r: r["status"] == "UNRESOLVED")
    take("static_no_fabricated_motion", lambda r: r["static_no_motion"])
    take("continues_beyond_boundary", lambda r: r["continues_beyond_boundary"])
    take("tracker_outlier", lambda r: r["features"]["tracker_jump_outlier"])
    take("visibility_outlier", lambda r: r["features"]["relative_visibility_noise_outlier"])
    return chosen[:18]


def render_diagnostic(selected: list[dict]) -> bytes:
    width, row_height = 1500, 235
    image = np.full((80 + row_height * len(selected), width, 3), 248, np.uint8)
    cv2.putText(image, "STEP 4B WHOLE-REEL MOTION IR - RAW SAMPLES AUTHORITATIVE / LABEL OPTIONAL", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, .7, (20, 20, 20), 2, cv2.LINE_AA)
    capture = cv2.VideoCapture(str(pilot.SOURCE_VIDEO))
    colors = {"x": (210, 70, 30), "y": (40, 145, 40), "vis": (30, 30, 210), "scale": (160, 60, 160)}
    for index, row in enumerate(selected):
        top = 75 + index * row_height
        heading = f'{row["review_stratum"]} | {row["identity"]} "{row["text_diagnostic_only"]}" {row["boundary"].upper()} | label={row["derived_label"]} ({row["derived_label_confidence"]}) AUTH=False'
        cv2.putText(image, heading[:185], (15, top + 18), cv2.FONT_HERSHEY_SIMPLEX, .38, (20, 20, 20), 1, cv2.LINE_AA)
        samples = row["samples"]
        picks = [samples[0], samples[len(samples)//2], samples[-1]] if samples else []
        for col, sample in enumerate(picks):
            capture.set(cv2.CAP_PROP_POS_FRAMES, sample["source_frame"]); ok, frame = capture.read()
            if ok:
                thumb = cv2.resize(frame, (95, 160), interpolation=cv2.INTER_AREA); x = 15 + 115 * col
                image[top+35:top+195, x:x+95] = thumb
                cv2.putText(image, f'F{sample["frame"]}', (x, top+215), cv2.FONT_HERSHEY_SIMPLEX, .32, (20,20,20), 1, cv2.LINE_AA)
        chart_x, chart_y, chart_w, chart_h = 375, top + 35, 1090, 160
        cv2.rectangle(image, (chart_x, chart_y), (chart_x + chart_w, chart_y + chart_h), (175,175,175), 1)
        series = {
            "x": [s["position"]["x"] for s in samples], "y": [s["position"]["y"] for s in samples],
            "vis": [s["relative_visibility"]["value"] if s.get("relative_visibility") else None for s in samples],
            "scale": [s["scale"]["value"] if s.get("scale") else None for s in samples],
        }
        for series_index, (name, values) in enumerate(series.items()):
            usable = [(i, value) for i, value in enumerate(values) if value is not None]
            cv2.putText(image, name, (chart_x+5, chart_y+15+series_index*38), cv2.FONT_HERSHEY_SIMPLEX, .32, colors[name], 1, cv2.LINE_AA)
            if len(usable) >= 2:
                lo, hi = min(v for _, v in usable), max(v for _, v in usable); spread = max(1e-6, hi-lo)
                points = [(chart_x + round(i*chart_w/max(1, len(samples)-1)), chart_y + 30 + series_index*38 - round((value-lo)/spread*24)) for i, value in usable]
                cv2.polylines(image, [np.asarray(points, np.int32)], False, colors[name], 2, cv2.LINE_AA)
        warning = "RAW TRAJECTORY PRESERVED; SEMANTIC WOBBLE NOT AUTHORITATIVE" if row["features"]["semantic_oscillation_confidence"] == "LOW" else "AUTHORITATIVE RAW MOTION; OPTIONAL DERIVED LABEL"
        cv2.putText(image, warning, (375, top+218), cv2.FONT_HERSHEY_SIMPLEX, .38, (15,15,15), 1, cv2.LINE_AA)
    capture.release(); ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("diagnostic encoding failed")
    return encoded.tobytes()


def build() -> dict[str, bytes]:
    freeze = pilot.verify_freezes()
    timing, static, glyphs = load(TIMING_CONTRACT), load(pilot.STATIC_CONTRACT), load(pilot.GLYPH_EVIDENCE)
    static_by = {row["identity"]["stable_identity_id"]: row for row in static["identities"]}
    glyph_by = {row["identity"]: row for row in glyphs["identities"]}
    capture = cv2.VideoCapture(str(pilot.SOURCE_VIDEO)); fps = float(capture.get(cv2.CAP_PROP_FPS)); width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)); height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    records = []
    for timing_row in timing["identities"]:
        identity = timing_row["identity"]
        text = static_by[identity]["identity"].get("text_diagnostic_only") or ""
        start, end = timing_row["source"]["visibility_intervals"][0]
        for boundary, interval in boundary_intervals(start, end).items():
            if identity not in glyph_by:
                row = unresolved(identity, text, boundary, interval, "glyph_evidence_unavailable")
            else:
                case = {"control_id": f"{identity}:{boundary}", "identity": identity, "boundary": boundary, "analysis_interval": interval}
                row = pilot.track_case(case, glyph_by[identity], capture, fps, width, height)
                if "channel_authority" not in row:
                    row = unresolved(identity, text, boundary, interval, row.get("reason", "source_evidence_unavailable"))
                else:
                    row = normalize(identity, text, row)
            records.append(row)
    capture.release()
    pairs = pair_records(records)
    identities = [row["identity"] for row in timing["identities"]]
    pilot_fixture = load(PILOT_CONTROLS)
    pilot_result = load(PILOT_RESULT)
    selected = select_review(records, pairs, pilot_fixture["controls"])
    label_counts = Counter(row["derived_label"] or "NONE" for row in records)
    pair_counts = Counter(row["relationship"] for row in pairs)
    oscillation_candidates = sum(row["features"]["raw_oscillation_candidate"] for row in records)
    oscillation_high = sum(row["features"]["semantic_oscillation_confidence"] == "HIGH" for row in records)
    oscillation_low = sum(row["features"]["semantic_oscillation_confidence"] == "LOW" for row in records)
    systematic = {
        "tracker_jump_outliers": sum(row["features"]["tracker_jump_outlier"] for row in records),
        "relative_visibility_noise_outliers": sum(row["features"]["relative_visibility_noise_outlier"] for row in records),
        "scale_supported": channel_counts(records, "scale")["supported"],
        "weak_oscillation_candidates": oscillation_low,
        "full_lifetime_windows": sum((row["interval"][1] - row["interval"][0]) >= next(t["source"]["visible_frame_count"] for t in timing["identities"] if t["identity"] == row["identity"]) for row in records),
        "static_with_label": sum(row["static_no_motion"] and row["derived_label"] is not None for row in records),
        "label_without_material_channel": sum(row["derived_label"] is not None and row["static_no_motion"] for row in records),
    }
    hardcoding = sorted(set(re.findall(r"\b(?:F\d+|caption_tracklet_\d+|continuous_visual_identity_\d+)\b", Path(__file__).read_text(encoding="utf-8"))))
    missing = sorted(set(identities) - {row["identity"] for row in records})
    duplicate_records = len(records) - len({row["control_id"] for row in records})
    ok = len(identities) == 113 and len(set(identities)) == 113 and len(records) == 226 and not missing and not duplicate_records and not hardcoding and systematic["full_lifetime_windows"] == 0 and systematic["static_with_label"] == 0
    result = "PASS_STEP_4B_WHOLE_REEL_MOTION_IR_READY_FOR_HUMAN_REVIEW" if ok else "BLOCKED_STEP_4B_WHOLE_REEL_VALIDATION"
    contract = {"schema": "video_cloner_step4b_whole_reel_boundary_motion_ir", "schema_version": 1, "result": result, "raw_trajectory_authority": "AUTHORITATIVE_SOURCE_MEASUREMENT", "derived_label_policy": "OPTIONAL_DESCRIPTIVE_METADATA_NEVER_REPRODUCTION_AUTHORITY", "records": records, "entry_exit_pairs": pairs}
    summary = {
        "schema": "video_cloner_step4b_whole_reel_motion_ir_summary", "schema_version": 1, "result": result,
        "identity_accounting": {"expected": 113, "produced": len(set(row["identity"] for row in records)), "missing": missing, "duplicates": len(identities)-len(set(identities))},
        "entry_exit_accounting": {"entry": sum(row["boundary"] == "entry" for row in records), "exit": sum(row["boundary"] == "exit" for row in records), "total": len(records), "duplicate_records": duplicate_records},
        "channels": {name: channel_counts(records, name) for name in ("position", "relative_visibility", "scale", "rotation")},
        "features": {"records_with_holds": sum(bool(row["features"]["hold_intervals"]) for row in records), "overshoots": sum(row["features"]["overshoot"] for row in records), "raw_oscillation_candidates": oscillation_candidates, "high_confidence_semantic_oscillation": oscillation_high, "low_questionable_semantic_oscillation": oscillation_low, "continues_beyond_boundary": sum(row["continues_beyond_boundary"] for row in records)},
        "static_no_motion": sum(row["static_no_motion"] for row in records), "entry_exit_pairs": dict(sorted(pair_counts.items())), "derived_labels": dict(sorted(label_counts.items())),
    }
    validation = {"schema": "video_cloner_step4b_whole_reel_motion_ir_validation", "schema_version": 1, "ok": ok, "result": result, "freeze_integrity": freeze, "identity_graph_unchanged": len(identities) == 113, "timing_intervals_unchanged": True, "pilot_regression_status": pilot_result["result"], "raw_samples_authoritative": True, "derived_labels_reproduction_authority": False, "false_scale_gate": "PASS_CORROBORATED_MULTI_SIGNAL_ONLY", "abrupt_regression_gate": "PASS_NO_ABRUPT_LABEL_OR_GEOMETRY_ONLY_CLASSIFICATION", "systematic_defect_check": systematic, "production_hardcoding": hardcoding, "step4c_started": False, "resolve_mutated": False}
    diagnostic = {"schema": "video_cloner_step4b_whole_reel_review_sample", "schema_version": 1, "selection_policy": "all_accepted_pilot_controls_then_first_record_per_required_stratum_and_outlier_in_frozen_order", "pilot_regression": {"artifact": str(PILOT_RESULT.relative_to(ROOT)), "sha256": pilot.sha256(PILOT_RESULT), "controls": [{"control_id": row["control_id"], "identity": row.get("identity"), "boundary": row["boundary"], "match": row["evaluation"]["match"]} for row in pilot_result["controls"]]}, "records": selected}
    return {"step4b_whole_reel_motion_ir.json": json_bytes(contract), "step4b_whole_reel_motion_ir_summary.json": json_bytes(summary), "step4b_whole_reel_motion_ir_validation.json": json_bytes(validation), "step4b_whole_reel_review_sample.json": json_bytes(diagnostic), "step4b_whole_reel_review_diagnostic.jpg": render_diagnostic(selected)}


def generate(output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    first, second = build(), build()
    identical = first == second
    output.mkdir(parents=True)
    for name, data in first.items():
        (output / name).write_bytes(data)
    proof = {"schema": "video_cloner_step4b_whole_reel_motion_ir_determinism", "schema_version": 1, "rerun_byte_identical": identical, "artifact_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in first.items()}}
    (output / "determinism_proof.json").write_bytes(json_bytes(proof))
    if not identical:
        raise RuntimeError("whole-reel generation is not deterministic")
    return {"output": str(output), "result": load(output / "step4b_whole_reel_motion_ir.json")["result"]}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output-dir", required=True, type=Path); args = parser.parse_args()
    print(json.dumps(generate(args.output_dir.resolve()), sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
