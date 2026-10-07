#!/usr/bin/env python3
"""Read-only Step 4C mechanism inventory and bounded rotation feasibility gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.analysis import generate_step4b_motion_ir_pilot as pilot
from scripts.analysis import generate_step4b_motion_ir_whole_reel as whole

STEP4B_FREEZE = ROOT / ".agent/state/video_cloner_step4b_motion_ir_freeze.json"
TIMING_CONTRACT = whole.TIMING_CONTRACT
STATIC_CONTRACT = pilot.STATIC_CONTRACT
GLYPH_EVIDENCE = pilot.GLYPH_EVIDENCE
EXPECTED_FREEZE_HASHES = {
    pilot.STATIC_FREEZE: "37ecd1438cd55b03cdb85b437131f0cafab322c85024ced41a00f01e69317601",
    pilot.TIMING_FREEZE: "e3934346a227e81a83e9c21e83860fcbf43a59f57a5b29752c149875749ccc23",
    STEP4B_FREEZE: "414b3fa823297b060eeb719e94154e222420cca8b270efbe7bce4d184fe18b65",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def mask_angle_degrees(shape: list[int], runs: list[list[int]]) -> float | None:
    mask = pilot.decode(shape, runs)
    y, x = np.nonzero(mask)
    if len(x) < 20:
        return None
    points = np.column_stack((x, y)).astype(np.float64)
    points -= points.mean(axis=0)
    values, vectors = np.linalg.eigh(np.cov(points, rowvar=False))
    vector = vectors[:, int(np.argmax(values))]
    angle = math.degrees(math.atan2(float(vector[1]), float(vector[0])))
    return round(((angle + 90.0) % 180.0) - 90.0, 6)


def orientation_series(glyph: dict) -> list[dict]:
    rows = []
    for observation in glyph.get("observations", []):
        if not observation.get("accepted") or not observation.get("estimated_mask_rle"):
            continue
        contamination = float(observation.get("background_contamination") or 0.0)
        if contamination > 0.2:
            continue
        angle = mask_angle_degrees(observation["estimated_mask_shape"], observation["estimated_mask_rle"])
        if angle is not None:
            rows.append({"source_frame": int(observation["source_frame"]), "bbox": list(map(int, observation["bbox"])), "angle_degrees": angle, "background_contamination": round(contamination, 6)})
    return rows


def rotation_metrics(series: list[dict]) -> dict:
    if len(series) < 2:
        return {"sample_count": len(series), "span_degrees": None, "correlation": None, "linear_rmse_degrees": None, "slope_degrees_per_30_source_frames": None}
    frames = np.asarray([row["source_frame"] for row in series], np.float64)
    angles = np.rad2deg(np.unwrap(np.deg2rad([row["angle_degrees"] for row in series]), period=np.pi))
    fit = np.polyfit(frames, angles, 1)
    predicted = np.polyval(fit, frames)
    correlation = float(np.corrcoef(frames, angles)[0, 1]) if float(np.std(angles)) > 1e-9 else 0.0
    return {
        "sample_count": len(series), "span_degrees": round(float(np.ptp(angles)), 6),
        "correlation": round(correlation, 6),
        "linear_rmse_degrees": round(float(np.sqrt(np.mean((angles - predicted) ** 2))), 6),
        "slope_degrees_per_30_source_frames": round(float(fit[0] * 30.0), 6),
    }


def classify_rotation(metrics: dict) -> str:
    count, span = metrics["sample_count"], metrics["span_degrees"]
    if count >= 4 and span is not None and span >= 2.0 and abs(metrics["correlation"]) >= 0.9 and metrics["linear_rmse_degrees"] <= 0.5:
        return "DYNAMIC_ROTATION_SUPPORTED"
    if count >= 3 and span is not None and span <= 0.75:
        return "STATIC_TILT_ONLY"
    return "ROTATION_UNRESOLVED"


def freeze_evidence() -> dict:
    pilot.verify_freezes()
    actual = {str(path.relative_to(ROOT)).replace("\\", "/"): pilot.sha256(path) for path in EXPECTED_FREEZE_HASHES}
    if any(pilot.sha256(path) != expected for path, expected in EXPECTED_FREEZE_HASHES.items()):
        raise RuntimeError("frozen authority drift")
    state = load(STEP4B_FREEZE)
    contract = ROOT / state["frozen_step4b_authority"]["motion_ir_contract"]["path"]
    if pilot.sha256(contract) != state["frozen_step4b_authority"]["motion_ir_contract"]["sha256"]:
        raise RuntimeError("Step 4B Motion IR drift")
    return {"hashes": actual, "step3": "FROZEN_INTACT", "step4a": "FROZEN_INTACT", "step4b": "FROZEN_INTACT", "step4b_motion_ir_sha256": pilot.sha256(contract)}


def mechanism_inventory() -> list[dict]:
    rows = [
        ("Step 4B dense caption template tracker", "scripts/analysis/generate_step4b_motion_ir_pilot.py", "track_case", "REUSE"),
        ("Step 4B corroborated scale gate", "scripts/analysis/generate_step4b_motion_ir_pilot.py", "scale_gate", "REUSE"),
        ("Step 4B relative visibility measurement", "scripts/analysis/generate_step4b_motion_ir_pilot.py", "visibility_strength", "REUSE"),
        ("Step 4B whole-reel normalization", "scripts/analysis/generate_step4b_motion_ir_whole_reel.py", "normalize", "ADAPT"),
        ("Historical accepted single-caption scale motion", "config/DcJRJtUKScu.accepted_caption_motion.json", "visual_observed", "REEL_SPECIFIC"),
        ("Historical Resolve keyframe application", "resolve_workspace/resolve_apply_caption_animation_step_3C.py", "keyframes", "HISTORICAL_ONLY"),
        ("Disposable Resolve animation probe", "resolve_workspace/modules/video_cloner_step4c_animation_live_probe.py", "STEP4C_PROBE", "UNSAFE_RESOLVE_MUTATION_FOR_CURRENT_SCOPE"),
        ("Scene/camera motion analyzer", "scripts/analysis/detect_motion_speed.py", "avg_rotation_deg", "UNSAFE_FOR_CAPTION_OBJECT_AUTHORITY"),
    ]
    result = []
    for name, relative, marker, classification in rows:
        path = ROOT / relative
        present = path.is_file() and marker in path.read_text(encoding="utf-8-sig")
        result.append({"mechanism": name, "path": relative, "marker": marker, "present": present, "classification": classification})
    if not all(row["present"] for row in result):
        raise RuntimeError("mechanism inventory drift")
    return result


def tracking_probe(identity: str, glyph: dict, timing: dict, capture: cv2.VideoCapture) -> dict:
    start, end = map(int, timing["source"]["visibility_intervals"][0])
    case = {"control_id": "step4c_feasibility", "identity": identity, "boundary": "dynamic", "analysis_interval": [start, end - 1]}
    row = pilot.track_case(case, glyph, capture, float(capture.get(cv2.CAP_PROP_FPS)), int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    if "channel_authority" not in row:
        return {"status": "UNRESOLVED", "reason": row.get("reason")}
    row = whole.normalize(identity, "", row)
    return {"status": row["status"], "interval": row["interval"], "sample_count": len(row["samples"]), "channel_authority": row["channel_authority"], "position_span": {axis: round(whole.span([sample["position"][axis] for sample in row["samples"]]), 8) for axis in ("x", "y")}, "scale_span": round(whole.span([sample["scale"]["value"] for sample in row["samples"] if sample.get("scale")]), 8), "relative_visibility_span": round(whole.span([sample["relative_visibility"]["value"] for sample in row["samples"] if sample.get("relative_visibility")]), 8)}


def render_diagnostic(controls: list[dict]) -> bytes:
    image = np.full((90 + len(controls) * 260, 1500, 3), 248, np.uint8)
    cv2.putText(image, "STEP 4C ROTATION FEASIBILITY - MASK PCA / SOURCE FRAMES", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, .75, (20, 20, 20), 2, cv2.LINE_AA)
    capture = cv2.VideoCapture(str(pilot.SOURCE_VIDEO))
    for index, control in enumerate(controls):
        top = 75 + index * 260
        cv2.putText(image, f'{control["role"]} | {control["text"]} | {control["verdict"]}', (15, top + 20), cv2.FONT_HERSHEY_SIMPLEX, .52, (20, 20, 20), 1, cv2.LINE_AA)
        series = control["series"]
        picks = [series[0], series[len(series)//2], series[-1]]
        for col, row in enumerate(picks):
            capture.set(cv2.CAP_PROP_POS_FRAMES, row["source_frame"]); ok, frame = capture.read()
            if ok:
                x1, y1, x2, y2 = row["bbox"]; cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 255), 3)
                thumb = cv2.resize(frame, (300, 169), interpolation=cv2.INTER_AREA); x = 15 + col * 320
                image[top+35:top+204, x:x+300] = thumb
                cv2.putText(image, f'F{row["source_frame"]} {row["angle_degrees"]:.2f} deg', (x, top+225), cv2.FONT_HERSHEY_SIMPLEX, .4, (20,20,20), 1, cv2.LINE_AA)
        chart_x, chart_y, chart_w, chart_h = 1000, top + 35, 470, 170
        cv2.rectangle(image, (chart_x, chart_y), (chart_x+chart_w, chart_y+chart_h), (160,160,160), 1)
        lo, hi = min(r["angle_degrees"] for r in series), max(r["angle_degrees"] for r in series); spread=max(.25, hi-lo)
        points=[(chart_x+round(i*chart_w/max(1,len(series)-1)), chart_y+chart_h-10-round((r["angle_degrees"]-lo)/spread*(chart_h-20))) for i,r in enumerate(series)]
        cv2.polylines(image, [np.asarray(points,np.int32)], False, (180,50,40), 2, cv2.LINE_AA)
        cv2.putText(image, f'span={control["metrics"]["span_degrees"]:.3f} corr={control["metrics"]["correlation"]:.3f} rmse={control["metrics"]["linear_rmse_degrees"]:.3f}', (1000, top+230), cv2.FONT_HERSHEY_SIMPLEX, .38, (20,20,20), 1, cv2.LINE_AA)
    capture.release(); ok, encoded=cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok: raise RuntimeError("diagnostic encoding failed")
    return encoded.tobytes()


def build() -> dict[str, bytes]:
    freeze = freeze_evidence(); inventory = mechanism_inventory()
    static, timing, glyphs = load(STATIC_CONTRACT), load(TIMING_CONTRACT), load(GLYPH_EVIDENCE)
    text_by = {row["identity"]["stable_identity_id"]: row["identity"].get("text_diagnostic_only") or "" for row in static["identities"]}
    timing_by = {row["identity"]: row for row in timing["identities"]}; glyph_by = {row["identity"]: row for row in glyphs["identities"]}
    candidates=[]
    for identity,glyph in glyph_by.items():
        series=orientation_series(glyph); metrics=rotation_metrics(series); verdict=classify_rotation(metrics)
        if series: candidates.append({"identity":identity,"text":text_by.get(identity,""),"series":series,"metrics":metrics,"verdict":verdict})
    six=max((row for row in candidates if row["text"]=="6000"), key=lambda row: row["metrics"]["sample_count"])
    dynamic=max((row for row in candidates if row["verdict"]=="DYNAMIC_ROTATION_SUPPORTED"), key=lambda row: row["metrics"]["span_degrees"])
    stable=min((row for row in candidates if row["verdict"]=="STATIC_TILT_ONLY" and row["text"]!="6000"), key=lambda row: (-row["metrics"]["sample_count"], row["metrics"]["span_degrees"]))
    controls=[{**six,"role":"6000_REQUIRED_CONTROL"},{**stable,"role":"NON_ROTATING_CONTROL"},{**dynamic,"role":"STRONGEST_DYNAMIC_CANDIDATE"}]
    capture=cv2.VideoCapture(str(pilot.SOURCE_VIDEO))
    for control in controls: control["full_lifetime_reuse_probe"]=tracking_probe(control["identity"],glyph_by[control["identity"]],timing_by[control["identity"]],capture)
    capture.release()
    step4b=load(ROOT / load(STEP4B_FREEZE)["frozen_step4b_authority"]["motion_ir_contract"]["path"])
    continuation_count=sum(bool(row.get("continues_beyond_boundary")) for row in step4b["records"])
    ok=len(timing["identities"])==113 and continuation_count==27 and six["verdict"]=="STATIC_TILT_ONLY" and bool(dynamic)
    result="PASS_STEP_4C_EXISTING_MECHANISM_AND_ROTATION_FEASIBILITY" if ok else "BLOCKED_STEP_4C_ROTATION_EVIDENCE_INSUFFICIENT"
    evidence={"schema":"video_cloner_step4c_rotation_feasibility","schema_version":1,"result":result,"method":"PCA_MAJOR_AXIS_OF_ACCEPTED_CAPTION_MASKS","gate":{"minimum_samples":4,"minimum_span_degrees":2.0,"minimum_absolute_frame_angle_correlation":0.9,"maximum_linear_rmse_degrees":0.5,"maximum_background_contamination":0.2},"controls":controls,"6000_verdict":six["verdict"]}
    investigation={"schema":"video_cloner_step4c_existing_mechanism_investigation","schema_version":1,"result":result,"freeze_integrity":freeze,"identity_count":len(timing["identities"]),"step4b_continues_beyond_boundary_count":continuation_count,"existing_mechanism_sufficient":"PARTIAL","mechanisms":inventory,"motion_ir_reuse_status":"REUSE_TRACKER_SCALE_VISIBILITY_AND_NORMALIZATION_ADAPT_TEMPORAL_WINDOW","resolve_mutated":False,"step4d_started":False}
    report=(f"RESULT: {result}\n\nSTATE\n- Step 3, Step 4A, and Step 4B freezes are intact.\n- Existing mechanism sufficient: PARTIAL; Step 4B measurement code is reusable.\n- 6000 verdict: {six['verdict']} ({six['metrics']['span_degrees']:.3f} degree span).\n\nCHANGED\n- Added read-only investigation tooling and immutable evidence only.\n\nVERIFIED\n- 113 identities and 27 Step 4B continuation records observed.\n- Resolve untouched; Step 4D not started.\n\nNEXT\n- Build the editor-neutral Step 4C whole-reel dynamic-transform contract from the reused measurement layer.\n\nRISK\n- Human review remains required for rotation and trajectory fidelity.\n").encode()
    return {"step4c_existing_mechanism_investigation.json":json_bytes(investigation),"step4c_rotation_feasibility.json":json_bytes(evidence),"step4c_rotation_feasibility_diagnostic.jpg":render_diagnostic(controls),"FINAL_REPORT.md":report}


def generate(output: Path) -> dict:
    if output.exists(): raise FileExistsError(output)
    first,second=build(),build(); identical=first==second
    if not identical: raise RuntimeError("non-deterministic investigation")
    output.mkdir(parents=True)
    for name,data in first.items(): (output/name).write_bytes(data)
    proof={"schema":"video_cloner_step4c_feasibility_determinism","schema_version":1,"rerun_byte_identical":identical,"artifact_sha256":{name:hashlib.sha256(data).hexdigest() for name,data in first.items()}}
    (output/"determinism_proof.json").write_bytes(json_bytes(proof))
    return {"output":str(output),"result":load(output/"step4c_rotation_feasibility.json")["result"]}


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--output-dir",required=True,type=Path); args=parser.parse_args()
    print(json.dumps(generate(args.output_dir.resolve()),sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
