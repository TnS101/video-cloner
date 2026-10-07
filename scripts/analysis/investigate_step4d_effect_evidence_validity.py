#!/usr/bin/env python3
"""Gate Step 4D candidates on effect-specific mask and evidence validity."""
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

from scripts.analysis import investigate_step4d_advanced_text_effects as prior

PRIOR_AUDIT = ROOT / ".agent/reports/VIDEO_CLONER_STEP4D_ADVANCED_TEXT_EFFECT_NECESSITY_INVESTIGATION_20260927_V1/20260927T190000000Z_investigation/step4d_effect_necessity_audit.json"
GLYPHS = prior.GLYPHS
COMPOSITION = prior.COMPOSITION
SOURCE = prior.SOURCE
EFFECTS = prior.CLASSES
VALIDITY = {"VALID_FOR_EFFECT", "PARTIAL_BUT_USABLE", "INVALID_FOR_EFFECT", "INSUFFICIENT_EVIDENCE"}
VERDICTS = {"SOURCE_REQUIRED", "NOT_PROVEN", "BLOCKED_BY_MASK_EVIDENCE", "UNSUPPORTED_WITH_CURRENT_EVIDENCE"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def top_candidates(audit: dict) -> dict[str, list[dict]]:
    selected = {}
    for effect in EFFECTS:
        rows = [row for row in audit["records"] if effect in row["candidate_classes"] and row.get("representative_source")]
        selected[effect] = sorted(rows, key=lambda row: (-row["scores"][effect], -row["evidence_quality"], row["identity"]))[:3]
    return selected


def observation_agreement(glyph: dict, frames: list[int]) -> dict:
    canonical = prior.decode(glyph["final_mask_shape"], glyph["final_mask_rle"]) > 0
    rows = []
    by_frame = {int(row["source_frame"]): row for row in glyph.get("observations", [])}
    for frame in frames:
        observation = by_frame.get(int(frame))
        if not observation or not observation.get("estimated_mask_rle"):
            continue
        observed = prior.decode(observation["estimated_mask_shape"], observation["estimated_mask_rle"]) > 0
        if observed.shape != canonical.shape:
            observed = cv2.resize(observed.astype(np.uint8), (canonical.shape[1], canonical.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
        intersection = np.count_nonzero(observed & canonical)
        union = np.count_nonzero(observed | canonical)
        rows.append({
            "source_frame": frame,
            "iou": round(intersection / max(1, union), 6),
            "canonical_coverage": round(intersection / max(1, np.count_nonzero(canonical)), 6),
            "observed_coverage": round(intersection / max(1, np.count_nonzero(observed)), 6),
            "background_contamination": round(float(observation.get("background_contamination") or 0), 6),
            "foreground_confidence": round(float(observation.get("foreground_confidence") or 0), 6),
        })
    return {
        "observations": rows,
        "median_iou": round(float(np.median([row["iou"] for row in rows])), 6) if rows else None,
        "median_canonical_coverage": round(float(np.median([row["canonical_coverage"] for row in rows])), 6) if rows else None,
    }


def case_frames(effect: str, record: dict) -> list[int]:
    if effect in {"clipping", "caption_occlusion"}:
        return [int(row["source_frame"]) for row in record.get("observations", [])][:3]
    return [int(record["representative_source"]["source_frame"])]


def mask_validity(effect: str, glyph: dict, record: dict, composition: dict) -> dict:
    frames = case_frames(effect, record)
    agreement = observation_agreement(glyph, frames)
    confidence = float(glyph.get("mask_confidence") or 0)
    unknown = float(glyph.get("unknown_ratio") or 0)
    contamination = float(glyph.get("contamination_score") or 0)
    overlap = float(glyph.get("overlap_risk") or 0)
    foreground_pixels = int(glyph.get("known_foreground_pixel_count") or 0)
    accepted = int(glyph.get("accepted_frame_count") or 0)
    median_iou = agreement["median_iou"]
    fragment = bool(glyph.get("physical_word_group_id"))
    defects = []

    if foreground_pixels < 50:
        defects.append("missing_foreground")
    if confidence < .20:
        defects.append("low_mask_confidence")
    if unknown > .60:
        defects.append("missing_or_unknown_foreground")
    if contamination > .35:
        defects.append("contamination")
    if median_iou is None:
        defects.append("observation_mask_missing")
    elif median_iou < .20:
        defects.append("source_mask_disagreement")
    if fragment:
        defects.append("fragment_only_evidence")

    status = "VALID_FOR_EFFECT"
    if any(item in defects for item in ("missing_foreground", "low_mask_confidence", "missing_or_unknown_foreground", "contamination", "source_mask_disagreement")):
        status = "INVALID_FOR_EFFECT"
    elif median_iou is None:
        status = "INSUFFICIENT_EVIDENCE"

    if effect in {"shadow", "glow"}:
        if overlap > .30 or contamination > .20:
            defects.append("untrustworthy_exterior_region")
            status = "INVALID_FOR_EFFECT"
        elif status == "VALID_FOR_EFFECT" and (confidence < .45 or unknown > .25 or fragment):
            status = "PARTIAL_BUT_USABLE"
    elif effect in {"texture", "gradient"}:
        if foreground_pixels < 150 or unknown > .45:
            defects.append("insufficient_glyph_interior")
            status = "INVALID_FOR_EFFECT"
        elif status == "VALID_FOR_EFFECT" and (confidence < .45 or unknown > .25 or fragment):
            status = "PARTIAL_BUT_USABLE"
    elif effect == "clipping":
        if accepted < 3 or len(agreement["observations"]) < 3:
            defects.append("temporal_evidence_missing")
            status = "INSUFFICIENT_EVIDENCE"
        elif status in {"VALID_FOR_EFFECT", "PARTIAL_BUT_USABLE"}:
            defects.append("static_masks_do_not_prove_reveal_boundary")
            status = "INSUFFICIENT_EVIDENCE"
    elif effect == "caption_occlusion":
        if composition["summary"]["overlap_relationships"] == 0 or composition["summary"]["authoritative_z_order_relationships"] == 0:
            defects.extend(["ownership_unknown", "authoritative_z_order_missing"])
            status = "INSUFFICIENT_EVIDENCE" if status != "INVALID_FOR_EFFECT" else status
        if accepted < 3:
            defects.append("temporal_evidence_missing")
            status = "INSUFFICIENT_EVIDENCE" if status != "INVALID_FOR_EFFECT" else status

    if status in {"INVALID_FOR_EFFECT", "INSUFFICIENT_EVIDENCE"}:
        verdict = "BLOCKED_BY_MASK_EVIDENCE"
    else:
        verdict = "NOT_PROVEN"
    return {
        "mask_validity": status,
        "mask_defects": sorted(set(defects)),
        "source_necessity_verdict": verdict,
        "source_effect_visually_present": "SUSPECTED_CANDIDATE_ONLY",
        "confidence": "LOW" if status in {"INVALID_FOR_EFFECT", "INSUFFICIENT_EVIDENCE"} else "MEDIUM",
        "metrics": {
            "mask_confidence": round(confidence, 6),
            "unknown_ratio": round(unknown, 6),
            "contamination_score": round(contamination, 6),
            "overlap_risk": round(overlap, 6),
            "known_foreground_pixels": foreground_pixels,
            "accepted_frame_count": accepted,
            "fragment_identity": fragment,
            "agreement": agreement,
        },
    }


def review_cases(audit: dict, glyphs: dict, composition: dict) -> list[dict]:
    glyph_by = {row["identity"]: row for row in glyphs["identities"]}
    cases = []
    for effect, records in top_candidates(audit).items():
        for rank, record in enumerate(records, start=1):
            glyph = glyph_by[record["identity"]]
            validity = mask_validity(effect, glyph, record, composition)
            cases.append({
                "identity": record["identity"],
                "effect_class": effect,
                "candidate_rank": rank,
                "source_frames": case_frames(effect, record),
                "effect_score": record["scores"][effect],
                "evidence_quality": record["evidence_quality"],
                "current_mask_purpose": "ACCEPTED_GLYPH_FONT_OWNERSHIP_AND_CANDIDATE_DISCOVERY_NOT_EFFECT_AUTHORITY",
                **validity,
                "evidence": {
                    "source_video": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
                    "glyph_evidence": str(GLYPHS.relative_to(ROOT)).replace("\\", "/"),
                    "prior_candidate_audit": str(PRIOR_AUDIT.relative_to(ROOT)).replace("\\", "/"),
                },
                "next_required_action": "BOUNDED_STEP4D_EFFECT_ROI_REPAIR" if validity["source_necessity_verdict"] == "BLOCKED_BY_MASK_EVIDENCE" else "HUMAN_SOURCE_NECESSITY_ADJUDICATION",
            })
    return cases


def class_verdicts(cases: list[dict]) -> dict:
    results = {}
    for effect in EFFECTS:
        rows = [row for row in cases if row["effect_class"] == effect]
        verdicts = {row["source_necessity_verdict"] for row in rows}
        if "SOURCE_REQUIRED" in verdicts:
            verdict = "SOURCE_REQUIRED"
        elif rows and all(row["mask_validity"] in {"INVALID_FOR_EFFECT", "INSUFFICIENT_EVIDENCE"} for row in rows):
            verdict = "BLOCKED_BY_MASK_EVIDENCE"
        elif rows:
            verdict = "NOT_PROVEN"
        else:
            verdict = "UNSUPPORTED_WITH_CURRENT_EVIDENCE"
        results[effect] = {
            "verdict": verdict,
            "reviewed_candidate_count": len(rows),
            "mask_validity_counts": dict(Counter(row["mask_validity"] for row in rows)),
            "reason": "effect-specific mask/ROI gate applied before source necessity authority",
        }
    return results


def panel(capture: cv2.VideoCapture, glyph: dict, frame_number: int, bbox: list[int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
    ok, frame = capture.read()
    if not ok:
        raise RuntimeError(f"source frame unavailable: {frame_number}")
    x1, y1, x2, y2 = map(int, bbox)
    h, w = max(1, y2-y1), max(1, x2-x1)
    pad = max(12, round(h*.65))
    rx1, ry1, rx2, ry2 = max(0, x1-pad), max(0, y1-pad), min(frame.shape[1], x2+pad), min(frame.shape[0], y2+pad)
    raw = frame[ry1:ry2, rx1:rx2].copy()
    mask = np.zeros(raw.shape[:2], np.uint8)
    unknown = np.zeros(raw.shape[:2], np.uint8)
    ox, oy = x1-rx1, y1-ry1
    mask[oy:oy+h, ox:ox+w] = cv2.resize(prior.decode(glyph["final_mask_shape"], glyph["final_mask_rle"]), (w,h), interpolation=cv2.INTER_NEAREST)
    if glyph.get("unknown_rle"):
        unknown[oy:oy+h, ox:ox+w] = cv2.resize(prior.decode(glyph["final_mask_shape"], glyph["unknown_rle"]), (w,h), interpolation=cv2.INTER_NEAREST)
    radius = max(1, round(min(h,w)*.05))
    ring = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius*2+1,radius*2+1)))
    ring = (ring > 0) & ~(mask > 0)
    mask_view = np.zeros_like(raw); mask_view[mask>0]=(255,255,255); mask_view[unknown>0]=(0,190,255); mask_view[ring]=(255,100,0)
    overlay = raw.copy(); overlay[mask>0] = (0.45*overlay[mask>0]+0.55*np.array([40,220,40])).astype(np.uint8); overlay[unknown>0]=(0.45*overlay[unknown>0]+0.55*np.array([0,190,255])).astype(np.uint8); overlay[ring]=(0.5*overlay[ring]+0.5*np.array([255,100,0])).astype(np.uint8)
    return raw, mask_view, overlay


def render(cases: list[dict], glyphs: dict) -> bytes:
    glyph_by={row["identity"]:row for row in glyphs["identities"]}
    rows=sum(min(3,len(case["source_frames"])) for case in cases)
    image=np.full((75+rows*245,1800,3),245,np.uint8)
    cv2.putText(image,"STEP 4D EFFECT EVIDENCE MASK VALIDITY - RAW / MASK / OVERLAY",(20,42),cv2.FONT_HERSHEY_SIMPLEX,.72,(20,20,20),2,cv2.LINE_AA)
    capture=cv2.VideoCapture(str(SOURCE)); top=65
    prior_by={row["identity"]:row for row in load(PRIOR_AUDIT)["records"]}
    for case in cases:
        glyph=glyph_by[case["identity"]]; record=prior_by[case["identity"]]
        bbox_by={int(row["source_frame"]):row["bbox"] for row in record.get("observations",[])}
        for frame in case["source_frames"][:3]:
            bbox=bbox_by.get(frame,record["representative_source"]["bbox"])
            raw,mask,overlay=panel(capture,glyph,frame,bbox)
            for col,picture in enumerate((raw,mask,overlay)):
                image[top+32:top+222,15+col*410:400+col*410]=cv2.resize(picture,(385,190),interpolation=cv2.INTER_AREA)
            title=f'{case["effect_class"]} #{case["candidate_rank"]} | {case["identity"]} | F{frame} | {case["mask_validity"]} | {case["source_necessity_verdict"]}'
            cv2.putText(image,title[:190],(15,top+20),cv2.FONT_HERSHEY_SIMPLEX,.39,(20,20,20),1,cv2.LINE_AA)
            cv2.putText(image,"white/green=foreground  amber=UNKNOWN  blue=exterior ring",(1245,top+56),cv2.FONT_HERSHEY_SIMPLEX,.34,(30,30,30),1,cv2.LINE_AA)
            cv2.putText(image,f'score={case["effect_score"]:.3f} quality={case["evidence_quality"]:.3f}',(1245,top+82),cv2.FONT_HERSHEY_SIMPLEX,.34,(30,30,30),1,cv2.LINE_AA)
            for line_no,defect in enumerate(case["mask_defects"][:6]): cv2.putText(image,defect,(1245,top+110+line_no*19),cv2.FONT_HERSHEY_SIMPLEX,.32,(20,20,160),1,cv2.LINE_AA)
            top+=245
    capture.release(); ok,encoded=cv2.imencode(".jpg",image,[cv2.IMWRITE_JPEG_QUALITY,92])
    if not ok: raise RuntimeError("diagnostic encoding failed")
    return encoded.tobytes()


def report(output: dict) -> bytes:
    lines = [
        f"RESULT: {output['result']}",
        "",
        f"FREEZE_INTEGRITY: {output['freeze_integrity']['status']}",
        f"CURRENT_STEP4D_STATUS: {output['current_step4d_status']}",
        f"MASK_VALIDITY_SUMMARY: {json.dumps(output['mask_validity_summary'], sort_keys=True)}",
        "",
        "REVIEWED_CASES",
    ]
    for case in output["cases"]:
        lines.extend([
            "",
            f"IDENTITY: {case['identity']}",
            f"EFFECT_CLASS: {case['effect_class']}",
            f"SOURCE_FRAME(S): {', '.join(map(str, case['source_frames']))}",
            f"CURRENT_MASK_PURPOSE: {case['current_mask_purpose']}",
            f"MASK_VALIDITY: {case['mask_validity']}",
            f"MASK_DEFECT_IF_ANY: {', '.join(case['mask_defects']) or 'NONE'}",
            f"SOURCE_EFFECT_VISUALLY_PRESENT: {case['source_effect_visually_present']}",
            f"SOURCE_NECESSITY_VERDICT: {case['source_necessity_verdict']}",
            f"CONFIDENCE: {case['confidence']}",
            f"EVIDENCE: {json.dumps(case['evidence'], sort_keys=True)}",
            f"NEXT_REQUIRED_ACTION: {case['next_required_action']}",
        ])
    lines.extend(["", "EFFECT_CLASS_VERDICTS"])
    for effect in EFFECTS:
        lines.append(f"{effect.upper()}_VERDICT: {output['effect_class_results'][effect]['verdict']}")
    lines.extend([
        "",
        f"SOURCE_REQUIRED_EFFECTS: {', '.join(output['source_required_effects']) or 'NONE'}",
        f"BLOCKED_BY_MASK_EVIDENCE_EFFECTS: {', '.join(output['blocked_by_mask_evidence_effects']) or 'NONE'}",
        f"NOT_PROVEN_EFFECTS: {', '.join(output['not_proven_effects']) or 'NONE'}",
        f"UNSUPPORTED_EFFECTS: {', '.join(output['unsupported_effects']) or 'NONE'}",
        f"MASK_REPAIR_REQUIRED: {'YES' if output['mask_repair_required'] else 'NO'}",
    ])
    if output["mask_repair_required"]:
        lines.append("BOUNDED_DEFECT_SET:")
        for row in output["bounded_repair_scope"]:
            lines.append(f"- {row['effect_class']} / {row['identity']}: {', '.join(row['defects'])}")
    lines.extend([
        f"PRODUCTION_EFFECT_MECHANISMS_ADDED: {output['production_effect_mechanisms_added']}",
        f"UPSTREAM_ARTIFACTS_CHANGED: {'YES' if output['upstream_artifacts_changed'] else 'NO'}",
        f"RESOLVE_MUTATED: {'YES' if output['resolve_mutated'] else 'NO'}",
        f"STEP_5_STARTED: {'YES' if output['step5_started'] else 'NO'}",
        "TESTS: focused gate plus affected Step 4D/composition regression",
        "DETERMINISM: rerun byte-identical; see determinism_proof.json",
        "DIAGNOSTIC_PATH: step4d_effect_evidence_validity_diagnostic.jpg",
        "AUDIT_PATH: step4d_effect_evidence_validity_audit.json",
        f"HUMAN_REVIEW_REQUIRED: {'YES' if output['human_review_required'] else 'NO'}",
        "NEXT_STEP_NAME_ONLY: Step 4D bounded effect-evidence mask repair" if output["mask_repair_required"] else "NEXT_STEP_NAME_ONLY: Step 4D human necessity acceptance / freeze",
        "",
    ])
    return "\n".join(lines).encode()


def build() -> dict[str,bytes]:
    freezes=prior.freeze_integrity(); audit=load(PRIOR_AUDIT); glyphs=load(GLYPHS); composition=load(COMPOSITION)
    cases=review_cases(audit,glyphs,composition); verdicts=class_verdicts(cases)
    counts=Counter(row["mask_validity"] for row in cases); blocked=[name for name,row in verdicts.items() if row["verdict"]=="BLOCKED_BY_MASK_EVIDENCE"]
    result="PASS_STEP_4D_EFFECT_EVIDENCE_VALIDITY_GATE_READY_FOR_HUMAN_REVIEW"
    output={"schema":"video_cloner_step4d_effect_evidence_validity_audit","schema_version":1,"result":result,"freeze_integrity":freezes,"current_step4d_status":"NECESSITY_CANDIDATES_EXIST_EFFECT_AUTHORITY_BLOCKED_PENDING_MASK_VALIDITY_REVIEW","measurement_dependencies":{"glyph_interior":["texture","gradient"],"glyph_exterior_local_background":["shadow","glow"],"temporal_evidence":["clipping","caption_occlusion"],"ownership_relationships":["caption_occlusion"],"source_frame_pixels":list(EFFECTS),"frozen_composition_evidence":["caption_occlusion"]},"cases":cases,"effect_class_results":verdicts,"mask_validity_summary":dict(counts),"source_required_effects":[name for name,row in verdicts.items() if row["verdict"]=="SOURCE_REQUIRED"],"blocked_by_mask_evidence_effects":blocked,"not_proven_effects":[name for name,row in verdicts.items() if row["verdict"]=="NOT_PROVEN"],"unsupported_effects":[name for name,row in verdicts.items() if row["verdict"]=="UNSUPPORTED_WITH_CURRENT_EVIDENCE"],"mask_repair_required":bool(blocked),"bounded_repair_scope":[{"identity":row["identity"],"effect_class":row["effect_class"],"defects":row["mask_defects"]} for row in cases if row["source_necessity_verdict"]=="BLOCKED_BY_MASK_EVIDENCE"],"production_effect_mechanisms_added":0,"upstream_artifacts_changed":False,"resolve_mutated":False,"step5_started":False,"human_review_required":True}
    artifacts={"step4d_effect_evidence_validity_audit.json":json_bytes(output),"step4d_effect_evidence_validity_diagnostic.jpg":render(cases,glyphs),"FINAL_REPORT.md":report(output)}
    return artifacts


def generate(output:Path)->dict:
    if output.exists(): raise FileExistsError(output)
    first,second=build(),build()
    if first!=second: raise RuntimeError("non-deterministic effect evidence audit")
    output.mkdir(parents=True)
    for name,data in first.items(): (output/name).write_bytes(data)
    proof={"schema":"video_cloner_step4d_effect_evidence_validity_determinism","schema_version":1,"rerun_byte_identical":True,"artifact_sha256":{name:hashlib.sha256(data).hexdigest() for name,data in first.items()}}
    (output/"determinism_proof.json").write_bytes(json_bytes(proof))
    return {"result":load(output/"step4d_effect_evidence_validity_audit.json")["result"],"output":str(output)}


def main()->int:
    parser=argparse.ArgumentParser(); parser.add_argument("--output-dir",required=True,type=Path); args=parser.parse_args()
    print(json.dumps(generate(args.output_dir.resolve()),sort_keys=True)); return 0


if __name__=="__main__": raise SystemExit(main())
