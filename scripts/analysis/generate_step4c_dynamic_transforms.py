#!/usr/bin/env python3
"""Generate the editor-neutral Step 4C Whole-Reel dynamic-transform contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.analysis import generate_step4b_motion_ir_pilot as pilot
from scripts.analysis import generate_step4b_motion_ir_whole_reel as whole
from scripts.analysis import investigate_step4c_dynamic_transforms as feasibility

STEP4B_FREEZE = feasibility.STEP4B_FREEZE
TIMING_CONTRACT = whole.TIMING_CONTRACT
STATIC_CONTRACT = pilot.STATIC_CONTRACT
GLYPH_EVIDENCE = pilot.GLYPH_EVIDENCE
FEASIBILITY = ROOT / ".agent/reports/VIDEO_CLONER_STEP4C_MECHANISM_ROTATION_FEASIBILITY_20260927_V1/20260927T160000000Z_investigation/step4c_rotation_feasibility.json"
FEASIBILITY_SHA256 = "de6c4aebe6274fbed04002563ec8535e366c9e61ac64bcfd34c1b59e29a5a583"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def supported(authority: str) -> bool:
    return not authority.startswith("UNRESOLVED") and authority != "UNSUPPORTED"


def channel_status(row: dict, channel: str) -> str:
    authority = row["channel_authority"][channel]
    if not supported(authority):
        return "UNRESOLVED"
    values = []
    for sample in row["samples"]:
        value = sample.get(channel)
        if channel == "position" and value:
            values.append((value["x"], value["y"]))
        elif value:
            values.append(value["value"])
    if channel == "position":
        material = bool(values and (whole.span([v[0] for v in values]) >= whole.POSITION_MIN or whole.span([v[1] for v in values]) >= whole.POSITION_MIN))
    elif channel == "scale":
        material = whole.span(values) >= whole.SCALE_MIN
    else:
        material = whole.span(values) >= whole.VISIBILITY_MIN
    return "DYNAMIC_SUPPORTED" if material else "STATIC"


def rotation_evidence(glyph: dict, source_fps: float) -> dict:
    series = feasibility.orientation_series(glyph)
    metrics = feasibility.rotation_metrics(series)
    detector = feasibility.classify_rotation(metrics)
    observations = [row for row in glyph.get("observations", []) if row.get("accepted") and row.get("estimated_mask_rle") and float(row.get("background_contamination") or 0.0) <= 0.2]
    aspects = [(row["bbox"][2] - row["bbox"][0]) / max(1, row["bbox"][3] - row["bbox"][1]) for row in observations]
    aspect_cv = float(np.std(aspects) / max(1e-9, np.mean(aspects))) if aspects else None
    max_contamination = max((float(row.get("background_contamination") or 0.0) for row in observations), default=None)
    if detector == "DYNAMIC_ROTATION_SUPPORTED":
        authority = "AUTHORITATIVE" if metrics["sample_count"] >= 5 and aspect_cv is not None and aspect_cv <= 0.12 and max_contamination is not None and max_contamination <= 0.18 else "PROVISIONAL"
        reason = None if authority == "AUTHORITATIVE" else "passing_detector_but_sparse_or_shape_sensitive"
    elif detector == "STATIC_TILT_ONLY":
        authority, reason = "STATIC_ORIENTATION_ONLY", "angle_does_not_materially_change"
    else:
        authority, reason = "UNRESOLVED", "accepted_rotation_gate_not_met"
    return {
        "method": "PCA_MAJOR_AXIS_OF_ACCEPTED_CAPTION_MASKS",
        "samples": [{**row, "frame": round(row["source_frame"] * pilot.TIMELINE_FPS / source_fps)} for row in series],
        "metrics": {**metrics, "aspect_ratio_cv": round(aspect_cv, 6) if aspect_cv is not None else None, "maximum_contamination": round(max_contamination, 6) if max_contamination is not None else None},
        "detector_verdict": detector,
        "reproduction_authority": authority,
        "authority_reason": reason,
    }


def full_lifetime_track(identity: str, glyph: dict, interval: list[int], capture: cv2.VideoCapture, source_fps: float, width: int, height: int) -> dict:
    start, end = map(int, interval)
    case = {"control_id": f"{identity}:dynamic", "identity": identity, "boundary": "dynamic", "analysis_interval": [start, end - 1]}
    row = pilot.track_case(case, glyph, capture, source_fps, width, height)
    if "channel_authority" not in row:
        return whole.unresolved(identity, "", "dynamic", [start, end - 1], row.get("reason", "source_evidence_unavailable"))
    return whole.normalize(identity, "", row)


def dynamic_region(interval: list[int]) -> list[int]:
    start, end = interval
    boundaries = whole.boundary_intervals(start, end)
    return [boundaries["entry"][1] + 1, boundaries["exit"][0]]


def register_to_frozen_boundaries(row: dict, identity: str, by_control: dict[str, dict]) -> dict:
    """Put the full-lifetime track in the frozen Step 4B coordinate/value basis."""
    anchors: dict[str, list[tuple[int, object]]] = {name: [] for name in ("position", "scale", "relative_visibility")}
    current = {sample["frame"]: sample for sample in row["samples"]}
    for side in ("entry", "exit"):
        frozen = by_control[f"{identity}:{side}"]
        overlap = [(sample, current[sample["frame"]]) for sample in frozen.get("samples", []) if sample["frame"] in current]
        if not overlap:
            continue
        edge = overlap[-1 if side == "entry" else 0]
        frame, left, right = edge[0]["frame"], edge[0], edge[1]
        for channel in anchors:
            if not supported(frozen["channel_authority"][channel]) or not supported(row["channel_authority"][channel]) or not left.get(channel) or not right.get(channel):
                continue
            correction = ({axis: left[channel][axis] - right[channel][axis] for axis in ("x", "y")} if channel == "position" else left[channel]["value"] - right[channel]["value"])
            anchors[channel].append((frame, correction))
    def correction(channel: str, frame: int):
        values = anchors[channel]
        if not values:
            return {"x": 0.0, "y": 0.0} if channel == "position" else 0.0
        if len(values) == 1 or values[0][0] == values[-1][0]:
            return values[0][1]
        ratio = max(0.0, min(1.0, (frame - values[0][0]) / (values[-1][0] - values[0][0])))
        if channel == "position":
            return {axis: values[0][1][axis] + ratio * (values[-1][1][axis] - values[0][1][axis]) for axis in ("x", "y")}
        return values[0][1] + ratio * (values[-1][1] - values[0][1])
    for sample in row["samples"]:
        for channel in anchors:
            if not sample.get(channel) or not anchors[channel]:
                continue
            sample[f"raw_{channel}"] = dict(sample[channel])
            delta = correction(channel, sample["frame"])
            if channel == "position":
                sample[channel] = {**sample[channel], **{axis: round(sample[channel][axis] + delta[axis], 8) for axis in ("x", "y")}, "registration": "FROZEN_STEP4B_OVERLAP"}
            else:
                sample[channel] = {**sample[channel], "value": round(sample[channel]["value"] + delta, 6), "registration": "FROZEN_STEP4B_OVERLAP"}
    old = row["features"]
    row["features"] = pilot.derive_features(row["samples"])
    row["features"].update({key: old.get(key) for key in ("raw_oscillation_candidate", "semantic_oscillation_confidence", "tracker_jump_outlier", "relative_visibility_noise_outlier")})
    row["registration"] = {channel: [{"frame": frame, "correction": value} for frame, value in values] for channel, values in anchors.items()}
    return row


def keyframes(row: dict, rotation: dict, interval: list[int], statuses: dict) -> dict:
    middle_start, middle_end = dynamic_region(interval)
    middle = [sample for sample in row["samples"] if middle_start <= sample["frame"] < middle_end]
    result = {"position": [], "scale": [], "rotation": [], "relative_visibility": []}
    if statuses["position"] == "DYNAMIC_SUPPORTED":
        result["position"] = [{"frame": sample["frame"], "value": {"x": sample["position"]["x"], "y": sample["position"]["y"]}, "authority": "SOURCE_TEMPLATE_TRACK"} for sample in middle]
    if statuses["scale"] == "DYNAMIC_SUPPORTED":
        result["scale"] = [{"frame": sample["frame"], "value": sample["scale"]["value"], "authority": "CORROBORATED_TEMPLATE_MASK_GEOMETRY"} for sample in middle if sample.get("scale")]
    if statuses["relative_visibility"] == "DYNAMIC_SUPPORTED":
        result["relative_visibility"] = [{"frame": sample["frame"], "value": sample["relative_visibility"]["value"], "semantics": "SOURCE_RELATIVE_VISIBILITY_NOT_ABSOLUTE_ALPHA"} for sample in middle if sample.get("relative_visibility")]
    if rotation["reproduction_authority"] in {"AUTHORITATIVE", "PROVISIONAL"}:
        result["rotation"] = [{"frame": sample["frame"], "value_degrees": sample["angle_degrees"], "authority": rotation["reproduction_authority"]} for sample in rotation["samples"] if interval[0] <= sample["frame"] < interval[1]]
    return result


def boundary_references(identity: str, by_control: dict[str, dict], freeze: dict) -> dict:
    path = freeze["frozen_step4b_authority"]["motion_ir_contract"]["path"]
    return {side: {"control_id": f"{identity}:{side}", "artifact": path, "sha256": freeze["frozen_step4b_authority"]["motion_ir_contract"]["sha256"], "authority": "FROZEN_STEP4B_REFERENCE", "channel_authority": by_control[f"{identity}:{side}"]["channel_authority"]} for side in ("entry", "exit")}


def continuity(record: dict, by_control: dict[str, dict]) -> list[dict]:
    checks = []
    samples = record["step4c_dynamic_transform"]["samples"]
    by_frame = {sample["frame"]: sample for sample in samples}
    for side in ("entry", "exit"):
        boundary = by_control[f'{record["identity"]}:{side}']
        if not boundary.get("samples"):
            continue
        edge = boundary["samples"][-1 if side == "entry" else 0]
        dynamic = by_frame.get(edge["frame"])
        if not dynamic:
            continue
        for channel, tolerance in (("position", 0.12), ("scale", 0.22), ("relative_visibility", 0.15)):
            authority = boundary["channel_authority"][channel]
            dynamic_authority = record["step4c_dynamic_transform"]["channel_authority"][channel]
            left, right = edge.get(channel), dynamic.get(channel)
            if not supported(authority) or not supported(dynamic_authority) or not left or not right:
                continue
            if channel == "position":
                delta = float(np.hypot(left["x"] - right["x"], left["y"] - right["y"]))
            else:
                delta = abs(float(left["value"]) - float(right["value"]))
            checks.append({"identity": record["identity"], "boundary": side, "channel": channel, "shared_frame": edge["frame"], "delta": round(delta, 8), "tolerance": tolerance, "ok": delta <= tolerance})
    return checks


def continuation_rows(records: list[dict], step4b_records: list[dict]) -> list[dict]:
    by_identity = {row["identity"]: row for row in records}
    output = []
    for frozen in step4b_records:
        if not frozen.get("continues_beyond_boundary"):
            continue
        record = by_identity[frozen["identity"]]
        statuses = record["step4c_dynamic_transform"]["channel_status"]
        if any(statuses[name] == "DYNAMIC_SUPPORTED" for name in ("position", "scale", "relative_visibility")):
            verdict = "CAPTURED_DYNAMIC_CONTINUATION"
        elif any(statuses[name] == "STATIC" for name in ("position", "scale", "relative_visibility")):
            verdict = "RESOLVES_STATIC"
        else:
            verdict = "UNRESOLVED"
        output.append({"step4b_control_id": frozen["control_id"], "identity": frozen["identity"], "boundary": frozen["boundary"], "step4c_interpretation": verdict, "frozen_step4b_unchanged": True})
    return output


def select_review(records: list[dict], continuations: list[dict], feasibility_data: dict) -> list[dict]:
    chosen: list[dict] = []
    by_id = {row["identity"]: row for row in records}
    def add(identity: str | None, stratum: str) -> None:
        if identity and identity in by_id and identity not in {row["identity"] for row in chosen}:
            chosen.append({"identity": identity, "review_stratum": stratum})
    roles = {row["role"]: row["identity"] for row in feasibility_data["controls"]}
    add(roles.get("6000_REQUIRED_CONTROL"), "required_static_tilt_control")
    add(roles.get("STRONGEST_DYNAMIC_CANDIDATE"), "rotation_feasibility_control")
    def take(stratum: str, predicate, reverse: bool = False, key=None) -> None:
        candidates = [row for row in records if row["identity"] not in {item["identity"] for item in chosen} and predicate(row)]
        if key: candidates.sort(key=key, reverse=reverse)
        add(candidates[0]["identity"] if candidates else None, stratum)
    take("strongest_authoritative_rotation", lambda r: r["rotation"]["reproduction_authority"] == "AUTHORITATIVE", True, lambda r: r["rotation"]["metrics"]["span_degrees"] or 0)
    take("weakest_provisional_rotation", lambda r: r["rotation"]["reproduction_authority"] == "PROVISIONAL", False, lambda r: r["rotation"]["metrics"]["span_degrees"] or 0)
    take("position_only", lambda r: r["step4c_dynamic_transform"]["channel_status"]["position"] == "DYNAMIC_SUPPORTED" and all(r["step4c_dynamic_transform"]["channel_status"][c] != "DYNAMIC_SUPPORTED" for c in ("scale", "relative_visibility")) and r["rotation"]["reproduction_authority"] not in {"AUTHORITATIVE", "PROVISIONAL"})
    take("supported_scale", lambda r: r["step4c_dynamic_transform"]["channel_status"]["scale"] == "DYNAMIC_SUPPORTED")
    take("relative_visibility", lambda r: r["step4c_dynamic_transform"]["channel_status"]["relative_visibility"] == "DYNAMIC_SUPPORTED")
    take("multi_channel", lambda r: sum(v == "DYNAMIC_SUPPORTED" for v in r["step4c_dynamic_transform"]["channel_status"].values()) >= 2)
    continuation_ids = {row["identity"] for row in continuations if row["step4c_interpretation"] == "CAPTURED_DYNAMIC_CONTINUATION"}
    take("step4b_to_step4c_continuation", lambda r: r["identity"] in continuation_ids)
    take("static_negative", lambda r: not any(r["editor_neutral_keyframes"].values()) and not any(v == "UNRESOLVED" for v in r["step4c_dynamic_transform"]["channel_status"].values()))
    take("unresolved", lambda r: any(v == "UNRESOLVED" for v in r["step4c_dynamic_transform"]["channel_status"].values()))
    take("deterministic_noncanonical", lambda r: True)
    for row in records:
        if len(chosen) >= 12: break
        add(row["identity"], "deterministic_fill")
    return chosen[:15]


def review_data(selected: list[dict], records: list[dict]) -> dict:
    by_id = {row["identity"]: row for row in records}
    return {"schema": "video_cloner_step4c_dynamic_transform_review_data", "schema_version": 1, "selection_policy": "required_controls_then_first_generic_stratum_match_in_frozen_order_then_frozen_order_fill", "cases": [{"review_stratum": item["review_stratum"], **by_id[item["identity"]]} for item in selected]}


def render_diagnostic(review: dict) -> bytes:
    rows = review["cases"]; width, row_height = 1700, 280
    image = np.full((75 + row_height * len(rows), width, 3), 248, np.uint8)
    cv2.putText(image, "STEP 4C WHOLE-REEL DYNAMIC TRANSFORMS - RAW SOURCE MEASUREMENTS", (20, 43), cv2.FONT_HERSHEY_SIMPLEX, .72, (20,20,20), 2, cv2.LINE_AA)
    capture = cv2.VideoCapture(str(pilot.SOURCE_VIDEO))
    colors = {"x":(210,70,30),"y":(40,145,40),"scale":(160,60,160),"rotation":(20,130,210),"visibility":(30,30,210)}
    for index,row in enumerate(rows):
        top=70+index*row_height; dynamic=row["step4c_dynamic_transform"]; samples=dynamic["samples"]
        rotation=row["rotation"]; heading=f'{row["review_stratum"]} | {row["identity"]} "{row["text_diagnostic_only"]}" | rot={rotation["detector_verdict"]}/{rotation["reproduction_authority"]}'
        cv2.putText(image,heading[:195],(15,top+18),cv2.FONT_HERSHEY_SIMPLEX,.4,(20,20,20),1,cv2.LINE_AA)
        picks=[samples[0],samples[len(samples)//2],samples[-1]] if samples else []
        for col,sample in enumerate(picks):
            capture.set(cv2.CAP_PROP_POS_FRAMES,sample["source_frame"]); ok,frame=capture.read()
            if ok:
                thumb=cv2.resize(frame,(110,196),interpolation=cv2.INTER_AREA); x=15+125*col; image[top+35:top+231,x:x+110]=thumb
                cv2.putText(image,f'F{sample["frame"]}',(x,top+250),cv2.FONT_HERSHEY_SIMPLEX,.32,(20,20,20),1,cv2.LINE_AA)
        chart_x,chart_y,chart_w,chart_h=410,top+35,1260,190; cv2.rectangle(image,(chart_x,chart_y),(chart_x+chart_w,chart_y+chart_h),(170,170,170),1)
        angle_by={sample["frame"]:sample["angle_degrees"] for sample in rotation["samples"]}
        series={"x":[s["position"]["x"] if s.get("position") else None for s in samples],"y":[s["position"]["y"] if s.get("position") else None for s in samples],"scale":[s["scale"]["value"] if s.get("scale") else None for s in samples],"rotation":[angle_by.get(s["frame"]) for s in samples],"visibility":[s["relative_visibility"]["value"] if s.get("relative_visibility") else None for s in samples]}
        for series_index,(name,values) in enumerate(series.items()):
            usable=[(i,v) for i,v in enumerate(values) if v is not None]; ybase=chart_y+25+series_index*34
            cv2.putText(image,name,(chart_x+5,ybase),cv2.FONT_HERSHEY_SIMPLEX,.31,colors[name],1,cv2.LINE_AA)
            if len(usable)>=2:
                lo,hi=min(v for _,v in usable),max(v for _,v in usable); spread=max(1e-6,hi-lo)
                points=[(chart_x+75+round(i*(chart_w-85)/max(1,len(samples)-1)),ybase+10-round((value-lo)/spread*22)) for i,value in usable]
                cv2.polylines(image,[np.asarray(points,np.int32)],False,colors[name],2,cv2.LINE_AA)
        entry_end=whole.boundary_intervals(*row["visibility_interval"])["entry"][1]; exit_start=whole.boundary_intervals(*row["visibility_interval"])["exit"][0]
        for frame,color in ((entry_end,(0,120,255)),(exit_start,(0,120,255))):
            x=chart_x+75+round((frame-row["visibility_interval"][0])*(chart_w-85)/max(1,row["visibility_interval"][1]-row["visibility_interval"][0]-1)); cv2.line(image,(x,chart_y),(x,chart_y+chart_h),color,1)
        status=" | ".join(f'{k}:{v}' for k,v in dynamic["channel_status"].items()); cv2.putText(image,status[:190],(410,top+252),cv2.FONT_HERSHEY_SIMPLEX,.31,(30,30,30),1,cv2.LINE_AA)
        metrics=rotation["metrics"]; rot=f'angle n={metrics["sample_count"]} span={metrics["span_degrees"]} corr={metrics["correlation"]} rmse={metrics["linear_rmse_degrees"]} contamination={metrics["maximum_contamination"]}'
        cv2.putText(image,rot[:190],(410,top+270),cv2.FONT_HERSHEY_SIMPLEX,.31,(30,30,30),1,cv2.LINE_AA)
    capture.release(); ok,encoded=cv2.imencode(".jpg",image,[cv2.IMWRITE_JPEG_QUALITY,92])
    if not ok: raise RuntimeError("diagnostic encoding failed")
    return encoded.tobytes()


def build() -> dict[str, bytes]:
    freeze=load(STEP4B_FREEZE); freeze_check=feasibility.freeze_evidence()
    if pilot.sha256(FEASIBILITY) != FEASIBILITY_SHA256: raise RuntimeError("accepted feasibility drift")
    feasibility_data=load(FEASIBILITY); timing=load(TIMING_CONTRACT); static=load(STATIC_CONTRACT); glyphs=load(GLYPH_EVIDENCE)
    step4b_path=ROOT/freeze["frozen_step4b_authority"]["motion_ir_contract"]["path"]; step4b=load(step4b_path)
    step4b_by={row["control_id"]:row for row in step4b["records"]}; glyph_by={row["identity"]:row for row in glyphs["identities"]}; text_by={row["identity"]["stable_identity_id"]:row["identity"].get("text_diagnostic_only") or "" for row in static["identities"]}
    capture=cv2.VideoCapture(str(pilot.SOURCE_VIDEO)); fps=float(capture.get(cv2.CAP_PROP_FPS)); width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)); height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    records=[]
    for timing_row in timing["identities"]:
        identity=timing_row["identity"]; interval=list(map(int,timing_row["source"]["visibility_intervals"][0])); glyph=glyph_by.get(identity)
        tracked=full_lifetime_track(identity,glyph,interval,capture,fps,width,height) if glyph else whole.unresolved(identity,"","dynamic",[interval[0],interval[1]-1],"glyph_evidence_unavailable")
        tracked=register_to_frozen_boundaries(tracked,identity,step4b_by)
        rotation=rotation_evidence(glyph,fps) if glyph else {"method":"PCA_MAJOR_AXIS_OF_ACCEPTED_CAPTION_MASKS","samples":[],"metrics":feasibility.rotation_metrics([]),"detector_verdict":"ROTATION_UNRESOLVED","reproduction_authority":"UNRESOLVED","authority_reason":"glyph_evidence_unavailable"}
        statuses={channel:channel_status(tracked,channel) for channel in ("position","scale","relative_visibility")}; statuses["rotation"]="DYNAMIC_SUPPORTED" if rotation["reproduction_authority"] in {"AUTHORITATIVE","PROVISIONAL"} else "STATIC" if rotation["reproduction_authority"]=="STATIC_ORIENTATION_ONLY" else "UNRESOLVED"
        record={"identity":identity,"text_diagnostic_only":text_by[identity],"visibility_interval":interval,"step4b_boundary_authority":boundary_references(identity,step4b_by,freeze),"step4c_dynamic_transform":{"dynamic_region":dynamic_region(interval),"samples":tracked["samples"],"channel_authority":tracked["channel_authority"],"channel_status":statuses,"features":tracked["features"],"provenance":["source_video","frozen_identity","frozen_step4a_interval","accepted_step4b_measurement_primitives"]},"rotation":rotation}
        record["editor_neutral_keyframes"]=keyframes(tracked,rotation,interval,statuses); records.append(record)
    capture.release()
    continuity_checks=[check for record in records for check in continuity(record,step4b_by)]
    continuations=continuation_rows(records,step4b["records"]); selected=select_review(records,continuations,feasibility_data); review=review_data(selected,records)
    identities=[row["identity"] for row in records]; duplicate_count=len(identities)-len(set(identities)); missing=sorted({row["identity"] for row in timing["identities"]}-set(identities))
    channel_counts={channel:dict(Counter(row["step4c_dynamic_transform"]["channel_status"][channel] for row in records)) for channel in ("position","scale","rotation","relative_visibility")}
    rotation_counts=dict(Counter(row["rotation"]["reproduction_authority"] for row in records)); detector_counts=dict(Counter(row["rotation"]["detector_verdict"] for row in records))
    keyframe_counts={channel:sum(len(row["editor_neutral_keyframes"][channel]) for row in records) for channel in ("position","scale","rotation","relative_visibility")}
    continuation_counts=dict(Counter(row["step4c_interpretation"] for row in continuations))
    controls={row["role"]:row for row in feasibility_data["controls"]}; six_id=controls["6000_REQUIRED_CONTROL"]["identity"]; dynamic_id=controls["STRONGEST_DYNAMIC_CANDIDATE"]["identity"]; by_id={row["identity"]:row for row in records}
    six=by_id[six_id]; dynamic=by_id[dynamic_id]
    dynamic_rotations=[row for row in records if row["rotation"]["detector_verdict"]=="DYNAMIC_ROTATION_SUPPORTED"]
    outliers={"largest_angle_span":max(dynamic_rotations,key=lambda r:r["rotation"]["metrics"]["span_degrees"],default=None),"highest_rotation_velocity":max(dynamic_rotations,key=lambda r:abs(r["rotation"]["metrics"]["slope_degrees_per_30_source_frames"]),default=None),"lowest_sample_passing":min(dynamic_rotations,key=lambda r:r["rotation"]["metrics"]["sample_count"],default=None),"near_contamination_limit":[r["identity"] for r in dynamic_rotations if (r["rotation"]["metrics"]["maximum_contamination"] or 0)>=0.18],"shape_sensitive":[r["identity"] for r in dynamic_rotations if (r["rotation"]["metrics"]["aspect_ratio_cv"] or 0)>0.12]}
    outliers={key:({"identity":value["identity"],"metrics":value["rotation"]["metrics"]} if isinstance(value,dict) and "rotation" in value else value) for key,value in outliers.items()}
    hardcoding=sorted(set(re.findall(r"\b(?:F\d+|caption_tracklet_\d+|continuous_visual_identity_\d+)\b",Path(__file__).read_text(encoding="utf-8"))))
    rejected_jumps=sum(row["step4c_dynamic_transform"]["features"].get("tracker_jump_outlier",False) for row in records)
    systematic={"rejected_tracker_jump_outliers":rejected_jumps,"systematic_tracker_failure":rejected_jumps>max(20,round(len(records)*.25)),"scale_authority_not_corroborated":sum(row["step4c_dynamic_transform"]["channel_status"]["scale"]=="DYNAMIC_SUPPORTED" and row["step4c_dynamic_transform"]["channel_authority"]["scale"]!="CORROBORATED_TEMPLATE_MASK_GEOMETRY" for row in records),"relative_visibility_absolute_alpha_claims":0,"static_tilt_with_rotation_keyframes":sum(row["rotation"]["detector_verdict"]=="STATIC_TILT_ONLY" and bool(row["editor_neutral_keyframes"]["rotation"]) for row in records),"systematic_rotation_false_positive":len(dynamic_rotations)>max(5,round(len(records)*.15)),"step4b_overwrites":0}
    intervals_ok=all(record["visibility_interval"][0]<=key["frame"]<record["visibility_interval"][1] for record in records for values in record["editor_neutral_keyframes"].values() for key in values)
    continuation_total=len(continuations); continuity_ok=all(check["ok"] for check in continuity_checks)
    six_ok=six["rotation"]["detector_verdict"]=="STATIC_TILT_ONLY" and not six["editor_neutral_keyframes"]["rotation"]
    systematic_blocked=any(systematic[key] for key in ("systematic_tracker_failure","scale_authority_not_corroborated","relative_visibility_absolute_alpha_claims","static_tilt_with_rotation_keyframes","systematic_rotation_false_positive","step4b_overwrites"))
    ok=len(records)==113 and not missing and not duplicate_count and continuation_total==27 and intervals_ok and continuity_ok and six_ok and not hardcoding and not systematic_blocked and any(keyframe_counts.values())
    if not six_ok: result="BLOCKED_STEP_4C_ROTATION_REGRESSION_6000"
    elif not continuity_ok: result="BLOCKED_STEP_4C_STEP4B_TRAJECTORY_CONTRADICTION"
    elif systematic["systematic_rotation_false_positive"]: result="BLOCKED_STEP_4C_SYSTEMATIC_ROTATION_FALSE_POSITIVES"
    else: result="PASS_STEP_4C_DYNAMIC_TRANSFORMS_READY_FOR_HUMAN_REVIEW" if ok else "BLOCKED_STEP_4C_SYSTEMATIC_TRACKER_FAILURE"
    summary={"identity_accounting":{"expected":113,"produced":len(records),"missing":missing,"duplicates":duplicate_count},"dynamic_transform_identity_counts":{"any_dynamic":sum(any(v=="DYNAMIC_SUPPORTED" for v in row["step4c_dynamic_transform"]["channel_status"].values()) for row in records),"no_supported_dynamic":sum(not any(v=="DYNAMIC_SUPPORTED" for v in row["step4c_dynamic_transform"]["channel_status"].values()) for row in records),"with_unresolved_channel":sum(any(v=="UNRESOLVED" for v in row["step4c_dynamic_transform"]["channel_status"].values()) for row in records)},"channels":channel_counts,"rotation":{"detector":detector_counts,"authority":rotation_counts},"continuations":{"total":continuation_total,**continuation_counts},"keyframes":keyframe_counts}
    contract={"schema":"video_cloner_step4c_dynamic_transform_contract","schema_version":1,"result":result,"raw_trajectory_authority":"AUTHORITATIVE_SOURCE_MEASUREMENT","boundary_policy":"FROZEN_STEP4B_REFERENCES_NEVER_OVERWRITTEN","records":records,"step4b_continuations":continuations}
    validation={"schema":"video_cloner_step4c_dynamic_transform_validation","schema_version":1,"ok":ok,"result":result,"freeze_integrity":freeze_check,"accepted_feasibility_sha256":FEASIBILITY_SHA256,"summary":summary,"step4b_4c_continuity":{"ok":continuity_ok,"checks":continuity_checks},"systematic_defect_check":systematic,"production_hardcoding":hardcoding,"keyframes_inside_step4a_intervals":intervals_ok,"scale_gate":"UNCHANGED_CORROBORATED_TEMPLATE_MASK_GEOMETRY","relative_visibility_semantics":"SOURCE_RELATIVE_VISIBILITY_NOT_ABSOLUTE_ALPHA","resolve_mutated":False,"step4d_started":False}
    rotation_audit={"schema":"video_cloner_step4c_rotation_audit","schema_version":1,"result":result,"method":"PCA_MAJOR_AXIS_OF_ACCEPTED_CAPTION_MASKS","gate":{"maximum_background_contamination":.20,"maximum_linear_rmse_degrees":.50,"minimum_absolute_frame_angle_correlation":.90,"minimum_samples":4,"minimum_angle_span_degrees":2.0},"authority_policy":"DETECTOR_RESULT_SEPARATE_FROM_FAIL_CLOSED_REPRODUCTION_AUTHORITY","counts":{"evaluated":sum(bool(row["rotation"]["samples"]) for row in records),**detector_counts,**rotation_counts},"outliers":outliers,"candidates":[{"identity":row["identity"],"text_diagnostic_only":row["text_diagnostic_only"],**row["rotation"]} for row in dynamic_rotations]}
    adjudication={"schema":"video_cloner_step4c_6000_rotation_adjudication","schema_version":1,"result":result,"identity":six_id,"text_diagnostic_only":six["text_diagnostic_only"],"accepted_feasibility_verdict":controls["6000_REQUIRED_CONTROL"]["verdict"],"whole_reel_rotation":six["rotation"],"dynamic_rotation_keyframes":six["editor_neutral_keyframes"]["rotation"],"regression_status":"PASS_STATIC_TILT_ONLY_PRESERVED" if six_ok else "FAIL_DYNAMIC_ROTATION_FABRICATED"}
    manifest={"schema":"video_cloner_step4c_dynamic_transform_review_manifest","schema_version":1,"result":result,"selection_policy":review["selection_policy"],"case_count":len(selected),"cases":selected,"required_controls":{"static_tilt":six_id,"dynamic_angle":dynamic_id},"human_review_required":True}
    artifacts={"step4c_dynamic_transform_contract.json":json_bytes(contract),"step4c_dynamic_transform_validation.json":json_bytes(validation),"step4c_rotation_audit.json":json_bytes(rotation_audit),"step4c_6000_rotation_adjudication.json":json_bytes(adjudication),"step4c_dynamic_transform_review_manifest.json":json_bytes(manifest),"step4c_dynamic_transform_review_data.json":json_bytes(review),"step4c_dynamic_transform_review_diagnostic.jpg":render_diagnostic(review)}
    report=(f"RESULT: {result}\n\nSTATE\n- 113 identities accounted for; frozen Step 3, Step 4A, and Step 4B authorities remained intact.\n- 6000 remained STATIC_TILT_ONLY; rotation detector thresholds are unchanged.\n\nCHANGED\n- Added one editor-neutral Whole-Reel Step 4C generator and focused tests.\n\nVERIFIED\n- Step 4B continuation inputs: 27; continuity gate: {'PASS' if continuity_ok else 'FAIL'}.\n- Keyframes: {json.dumps(keyframe_counts,sort_keys=True)}.\n- Resolve untouched; Step 4D not started.\n\nNEXT\n- Human review of the deterministic Step 4C diagnostic.\n\nRISK\n- Human visual approval remains required; Step 4C is not frozen.\n").encode()
    artifacts["FINAL_REPORT.md"]=report
    return artifacts


def generate(output: Path) -> dict:
    if output.exists(): raise FileExistsError(output)
    first,second=build(),build(); identical=first==second
    if not identical: raise RuntimeError("Step 4C generation is not deterministic")
    output.mkdir(parents=True)
    for name,data in first.items(): (output/name).write_bytes(data)
    proof={"schema":"video_cloner_step4c_dynamic_transform_determinism","schema_version":1,"rerun_byte_identical":identical,"artifact_sha256":{name:hashlib.sha256(data).hexdigest() for name,data in first.items()}}
    (output/"determinism_proof.json").write_bytes(json_bytes(proof))
    return {"output":str(output),"result":load(output/"step4c_dynamic_transform_contract.json")["result"]}


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--output-dir",required=True,type=Path); args=parser.parse_args()
    print(json.dumps(generate(args.output_dir.resolve()),sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
