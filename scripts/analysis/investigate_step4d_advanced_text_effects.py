#!/usr/bin/env python3
"""Read-only, hypothesis-neutral Step 4D necessity investigation."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
FREEZES = {
    ROOT / ".agent/state/video_cloner_static_caption_freeze.json": "37ecd1438cd55b03cdb85b437131f0cafab322c85024ced41a00f01e69317601",
    ROOT / ".agent/state/video_cloner_timing_persistence_freeze.json": "e3934346a227e81a83e9c21e83860fcbf43a59f57a5b29752c149875749ccc23",
    ROOT / ".agent/state/video_cloner_step4b_motion_ir_freeze.json": "414b3fa823297b060eeb719e94154e222420cca8b270efbe7bce4d184fe18b65",
    ROOT / ".agent/state/video_cloner_step4c_dynamic_transforms_freeze.json": "64f1493ec24f54968f90a66bc72b8346c5cf1af8acbc8a5661f02df7c800a54f",
}
STATIC = ROOT / ".agent/reports/VIDEO_CLONER_STEP2F_FONT_AUTHORITY_CALIBRATION_20260927/20260927T020000000Z_calibrated/whole_reel_static_style_contract_calibrated.json"
GLYPHS = ROOT / ".agent/reports/VIDEO_CLONER_STEP2B1_FINAL_MULTI_OBJECT_MASK_ISOLATION_REPAIR_20260927/20260927T000000000Z_bounded/reel2_glyph_evidence_v2_mask_isolation_corrected.json"
COMPOSITION = ROOT / ".agent/reports/VIDEO_CLONER_STEP2E_COMPOSITION_RELATIONSHIPS_20260925/20260925T220000000Z_source_graph/step2e_composition_relationships.json"
LEGACY_STYLE = ROOT / "data/DcJRJtUKScu/analysis/DcJRJtUKScu_caption_style.json"
SOURCE = ROOT / "input/DcJRJtUKScu.mp4"
CLASSES = ("shadow", "glow", "texture", "gradient", "clipping", "caption_occlusion")
ALLOWED_CLASSIFICATIONS = {"SOURCE_REQUIRED", "ALREADY_SOLVED", "POSSIBLE_BUT_UNPROVEN", "NOT_PRESENT", "NON_CAPTION_VFX", "UNSUPPORTED"}
ALLOWED_IDENTITY_STATUSES = {"NO_ADVANCED_EFFECT_EVIDENCE", "ADVANCED_EFFECT_CANDIDATE", "SOURCE_REQUIRED_ADVANCED_EFFECT", "UNRESOLVED_ADVANCED_EFFECT", "NON_CAPTION_VFX", "UNSUPPORTED_SOURCE_REQUIRED_EFFECT"}
THRESHOLDS = {"shadow": .12, "glow": .10, "texture": .10, "gradient": .08, "clipping": .18, "caption_occlusion": .20}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def decode(shape: list[int], runs: list[list[int]]) -> np.ndarray:
    flat = np.zeros(int(np.prod(shape)), np.uint8)
    for start, length in runs:
        flat[int(start):int(start) + int(length)] = 255
    return flat.reshape(shape)


def freeze_integrity() -> dict:
    actual = {str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path) for path in FREEZES}
    if any(sha256(path) != expected for path, expected in FREEZES.items()):
        raise RuntimeError("frozen authority drift")
    return {"status": "PASS", "hashes": actual}


def mechanism_inventory(legacy: dict, composition: dict) -> tuple[list[dict], dict]:
    groups = legacy["subtitle_groups"]
    collision = {
        "group_count": len(groups),
        "has_shadow_count": sum(bool(row.get("has_shadow")) for row in groups),
        "has_dark_stroke_count": sum(bool(row.get("has_dark_stroke")) for row in groups),
        "same_shadow_and_stroke_color_count": sum(row.get("estimated_shadow_color") == row.get("estimated_stroke_color") for row in groups),
        "verdict": "UNSAFE_STROKE_DARK_EDGE_CONFLATED_WITH_SHADOW",
    }
    mechanisms = [
        {"mechanism": "legacy caption shadow heuristic", "path": str(LEGACY_STYLE.relative_to(ROOT)).replace("\\", "/"), "classification": "UNSAFE", "evidence": collision},
        {"mechanism": "frozen ordinary fill/stroke authority", "path": str(STATIC.relative_to(ROOT)).replace("\\", "/"), "classification": "ALREADY_FROZEN"},
        {"mechanism": "accepted glyph ownership masks", "path": str(GLYPHS.relative_to(ROOT)).replace("\\", "/"), "classification": "REUSE_FOR_CANDIDATE_DISCOVERY_ONLY"},
        {"mechanism": "composition overlap and z-order graph", "path": str(COMPOSITION.relative_to(ROOT)).replace("\\", "/"), "classification": "ALREADY_FROZEN", "evidence": {"proven_overlap_relationships": composition["summary"]["overlap_relationships"], "authoritative_z_order_relationships": composition["summary"]["authoritative_z_order_relationships"], "ownership_candidates_not_promoted": composition["summary"]["ownership_interaction_candidates_not_promoted_to_overlap"]}},
        {"mechanism": "historical Reel 1 foreground RGBA occlusion", "path": ".agent/reports/VIDEO_CLONER_PHASE4C2_ACCEPTED_OCCLUSION_V4_INTEGRATION", "classification": "REEL_SPECIFIC_NON_CAPTION_VFX"},
        {"mechanism": "historical flash transitions", "path": ".agent/reports/VIDEO_CLONER_PHASE4C1_ACCEPTED_FLASH_V4_INTEGRATION", "classification": "NON_CAPTION_VFX"},
    ]
    return mechanisms, collision


def shift(mask: np.ndarray, dx: int, dy: int) -> np.ndarray:
    result = np.zeros_like(mask)
    ys = slice(max(0, dy), mask.shape[0] + min(0, dy))
    xs = slice(max(0, dx), mask.shape[1] + min(0, dx))
    source_y = slice(max(0, -dy), mask.shape[0] - max(0, dy))
    source_x = slice(max(0, -dx), mask.shape[1] - max(0, dx))
    result[ys, xs] = mask[source_y, source_x]
    return result


def representative_observations(row: dict) -> list[dict]:
    accepted = [item for item in row.get("observations", []) if item.get("accepted")]
    if len(accepted) <= 3:
        return accepted
    return [accepted[0], accepted[len(accepted) // 2], accepted[-1]]


def observation_metrics(capture: cv2.VideoCapture, row: dict, observation: dict) -> dict:
    capture.set(cv2.CAP_PROP_POS_FRAMES, int(observation["source_frame"]))
    ok, frame = capture.read()
    if not ok:
        raise RuntimeError(f"source frame unavailable: {observation['source_frame']}")
    x1, y1, x2, y2 = map(int, observation["bbox"])
    h, w = max(1, y2-y1), max(1, x2-x1)
    pad = max(8, round(h * .5))
    rx1, ry1, rx2, ry2 = max(0, x1-pad), max(0, y1-pad), min(frame.shape[1], x2+pad), min(frame.shape[0], y2+pad)
    roi = frame[ry1:ry2, rx1:rx2]
    mask = np.zeros(roi.shape[:2], np.uint8)
    resized = cv2.resize(decode(row["final_mask_shape"], row["final_mask_rle"]), (w, h), interpolation=cv2.INTER_NEAREST)
    ox, oy = x1-rx1, y1-ry1
    mask[oy:oy+h, ox:ox+w] = resized
    radius = max(1, round(min(h, w) * .035))
    broad = max(radius+2, round(min(h, w) * .12))
    small_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius*2+1, radius*2+1))
    broad_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (broad*2+1, broad*2+1))
    dilated = cv2.dilate(mask, small_kernel) > 0
    broad_dilated = cv2.dilate(mask, broad_kernel) > 0
    core = cv2.erode(mask, small_kernel) > 0
    if np.count_nonzero(core) < 20:
        core = mask > 0
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
    background = ~broad_dilated
    background_level = float(np.median(gray[background])) if np.any(background) else float(np.median(gray))
    offsets = [(dx, dy) for dy in range(-broad, broad+1, max(1, broad//2)) for dx in range(-broad, broad+1, max(1, broad//2)) if dx or dy]
    shadow_scores = []
    for dx, dy in offsets:
        displaced = (shift(mask, dx, dy) > 0) & ~dilated
        if np.count_nonzero(displaced) >= 20:
            shadow_scores.append(max(0.0, (background_level - float(np.mean(gray[displaced]))) / 255.0))
    narrow_ring = dilated & ~(mask > 0)
    broad_ring = broad_dilated & ~dilated
    narrow_brightness = float(np.mean(gray[narrow_ring])) if np.any(narrow_ring) else background_level
    broad_brightness = float(np.mean(gray[broad_ring])) if np.any(broad_ring) else background_level
    glow = max(0.0, ((narrow_brightness + broad_brightness) / 2.0 - background_level) / 255.0)
    yy, xx = np.nonzero(core)
    values = gray[core]
    if len(values) >= 20:
        design = np.column_stack((np.ones(len(values)), xx / max(1, roi.shape[1]-1), yy / max(1, roi.shape[0]-1)))
        fit = design @ np.linalg.lstsq(design, values, rcond=None)[0]
        total = float(np.sum((values-values.mean())**2))
        gradient = (1.0-float(np.sum((values-fit)**2))/total if total > 1e-6 else 0.0) * float(np.ptp(fit)) / 255.0
        texture = float(np.std(values-fit)) / 255.0
    else:
        gradient = texture = 0.0
    clipping = 0.0
    if observation.get("estimated_mask_rle"):
        observed = decode(observation["estimated_mask_shape"], observation["estimated_mask_rle"]) > 0
        canonical = decode(row["final_mask_shape"], row["final_mask_rle"]) > 0
        if observed.shape != canonical.shape:
            observed = cv2.resize(observed.astype(np.uint8), (canonical.shape[1], canonical.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
        clipping = max(0.0, 1.0 - np.count_nonzero(observed & canonical) / max(1, np.count_nonzero(canonical)))
    return {"source_frame": int(observation["source_frame"]), "bbox": [x1, y1, x2, y2], "background_contamination": round(float(observation.get("background_contamination") or 0), 6), "shadow": round(max(shadow_scores, default=0.0), 6), "glow": round(glow, 6), "gradient": round(max(0.0, gradient), 6), "texture": round(texture, 6), "clipping": round(clipping, 6)}


def identity_evidence(row: dict, capture: cv2.VideoCapture) -> dict:
    observations = [observation_metrics(capture, row, item) for item in representative_observations(row)]
    scores = {name: max((item[name] for item in observations), default=0.0) for name in ("shadow", "glow", "gradient", "texture", "clipping")}
    scores["caption_occlusion"] = max(float(row.get("overlap_risk") or 0), float(row.get("overlap_occlusion_ratio") or 0))
    quality = max(0.0, 1.0-float(row.get("contamination_score") or 0))
    best = min(observations, key=lambda item: (item["background_contamination"], item["source_frame"])) if observations else None
    candidates = [name for name in CLASSES if best and scores[name] >= THRESHOLDS[name]]
    return {"identity": row["identity"], "status": "ADVANCED_EFFECT_CANDIDATE" if candidates else "NO_ADVANCED_EFFECT_EVIDENCE", "candidate_classes": candidates, "scores": {key: round(value, 6) for key, value in scores.items()}, "evidence_quality": round(quality, 6), "representative_source": {"source_frame": best["source_frame"], "bbox": best["bbox"]} if best else None, "observations": observations, "provenance": [str(GLYPHS.relative_to(ROOT)).replace("\\", "/"), str(SOURCE.relative_to(ROOT)).replace("\\", "/")]}


def classify_effects(records: list[dict]) -> dict:
    results = {}
    for effect in CLASSES:
        candidates = sorted((row for row in records if effect in row["candidate_classes"]), key=lambda row: (-row["scores"][effect], -row["evidence_quality"], row["identity"]))
        strongest = candidates[0] if candidates else None
        classification = "POSSIBLE_BUT_UNPROVEN" if candidates else "NOT_PRESENT"
        results[effect] = {
            "classification": classification,
            "candidate_count": len(candidates),
            "strongest_candidate": strongest["identity"] if strongest else None,
            "strongest_score": strongest["scores"][effect] if strongest else 0.0,
            "evidence_quality": strongest["evidence_quality"] if strongest else None,
            "reason": "candidate heuristic surfaced source examples; human adjudication required" if candidates else "no meaningful candidate found by bounded source search",
            "evidence_for": ([{"identity": row["identity"], "score": row["scores"][effect], "source": row["representative_source"], "provenance": row["provenance"]} for row in candidates[:3]]),
            "evidence_against": "candidate metric is non-authoritative and may reflect stroke, contamination, antialiasing, compression, motion, or background",
        }
    results["shadow"]["reason"] += "; legacy shadow heuristic remains unsafe and supplies no authority"
    results["clipping"]["evidence_against"] += "; Step 4B/4C visibility and partial ownership are not mask-reveal proof"
    results["caption_occlusion"]["evidence_against"] += "; frozen graph has zero proven overlap and zero authoritative z-order"
    return results


def select_review(records: list[dict], effects: dict) -> list[dict]:
    by_id = {row["identity"]: row for row in records}
    selected: list[tuple[str, str]] = []
    for effect in CLASSES:
        identity = effects[effect]["strongest_candidate"]
        if identity:
            selected.append((identity, f"STRONGEST_{effect.upper()}_CANDIDATE"))
    negatives = sorted((row for row in records if not row["candidate_classes"] and row["representative_source"]), key=lambda row: (-row["evidence_quality"], row["identity"]))[:3]
    selected.extend((row["identity"], "HIGH_QUALITY_NEGATIVE_CONTROL") for row in negatives)
    ambiguities = sorted((row for row in records if row["representative_source"]), key=lambda row: (row["evidence_quality"], row["identity"]))[:2]
    selected.extend((row["identity"], "HIGH_CONTAMINATION_AMBIGUITY_CONTROL") for row in ambiguities)
    merged: dict[str, list[str]] = {}
    for identity, role in selected:
        merged.setdefault(identity, []).append(role)
    if len(merged) < 8:
        for row in sorted((row for row in records if row["representative_source"]), key=lambda row: (-max(row["scores"].values()), row["identity"])):
            merged.setdefault(row["identity"], ["ADDITIONAL_STRONG_SOURCE_CANDIDATE"])
            if len(merged) >= 8:
                break
    return [{**by_id[identity], "review_roles": roles} for identity, roles in list(merged.items())[:15]]


def render(review: list[dict], glyph_by: dict[str, dict]) -> bytes:
    image = np.full((80+len(review)*255, 1500, 3), 245, np.uint8)
    cv2.putText(image, "STEP 4D UNBIASED NECESSITY CANDIDATES - SOURCE / GLYPH MASK", (20, 42), cv2.FONT_HERSHEY_SIMPLEX, .72, (20,20,20), 2, cv2.LINE_AA)
    capture = cv2.VideoCapture(str(SOURCE))
    for index, case in enumerate(review):
        top = 70+index*255; source = case["representative_source"]
        capture.set(cv2.CAP_PROP_POS_FRAMES, source["source_frame"]); ok, frame = capture.read()
        if not ok: raise RuntimeError(f"source frame unavailable: {source['source_frame']}")
        x1,y1,x2,y2 = source["bbox"]; pad=max(10,round((y2-y1)*.7))
        crop=frame[max(0,y1-pad):min(frame.shape[0],y2+pad),max(0,x1-pad):min(frame.shape[1],x2+pad)]
        image[top+38:top+228,15:615]=cv2.resize(crop,(600,190),interpolation=cv2.INTER_AREA)
        glyph=glyph_by[case["identity"]]; mask=decode(glyph["final_mask_shape"],glyph["final_mask_rle"])
        image[top+38:top+228,640:1240]=cv2.cvtColor(cv2.resize(mask,(600,190),interpolation=cv2.INTER_NEAREST),cv2.COLOR_GRAY2BGR)
        heading=f'{case["identity"]} | {" + ".join(case["review_roles"])} | F{source["source_frame"]}'
        cv2.putText(image,heading[:180],(15,top+21),cv2.FONT_HERSHEY_SIMPLEX,.4,(20,20,20),1,cv2.LINE_AA)
        details=f'candidates={case["candidate_classes"]} quality={case["evidence_quality"]}'
        cv2.putText(image,details[:90],(1255,top+90),cv2.FONT_HERSHEY_SIMPLEX,.3,(30,30,30),1,cv2.LINE_AA)
        for line_no,(name,value) in enumerate(case["scores"].items()):
            cv2.putText(image,f'{name}: {value:.3f}',(1255,top+112+line_no*18),cv2.FONT_HERSHEY_SIMPLEX,.3,(30,30,30),1,cv2.LINE_AA)
    capture.release(); ok, encoded=cv2.imencode(".jpg",image,[cv2.IMWRITE_JPEG_QUALITY,92])
    if not ok: raise RuntimeError("diagnostic encoding failed")
    return encoded.tobytes()


def build() -> dict[str, bytes]:
    freezes=freeze_integrity(); static,glyphs,composition,legacy=load(STATIC),load(GLYPHS),load(COMPOSITION),load(LEGACY_STYLE)
    static_ids=[row["identity"]["stable_identity_id"] for row in static["identities"]]; glyph_by={row["identity"]:row for row in glyphs["identities"]}
    if len(static_ids)!=113 or len(set(static_ids))!=113 or set(static_ids)!=set(glyph_by): raise RuntimeError("113-identity accounting failed")
    mechanisms,collision=mechanism_inventory(legacy,composition)
    capture=cv2.VideoCapture(str(SOURCE)); records=[identity_evidence(glyph_by[identity],capture) for identity in static_ids]; capture.release()
    effects=classify_effects(records); review=select_review(records,effects)
    class_counts=Counter(row["classification"] for row in effects.values()); identity_counts=Counter(row["status"] for row in records)
    result="PASS_STEP_4D_NECESSITY_INVESTIGATION_READY_FOR_HUMAN_ADJUDICATION"
    summary={name.lower():class_counts.get(name,0) for name in ALLOWED_CLASSIFICATIONS}
    audit={"schema":"video_cloner_step4d_effect_necessity_audit","schema_version":2,"result":result,"methodology":"BOUNDED_NON_AUTHORITATIVE_HYPOTHESIS_RANKING_FOR_HUMAN_ADJUDICATION","identity_accounting":{"expected":113,"produced":len(records),"missing":[],"duplicates":0},"effect_classes":effects,"records":records,"identity_classification_counts":dict(identity_counts),"summary":summary,"human_adjudication_required":True}
    validation={"schema":"video_cloner_step4d_necessity_investigation_validation","schema_version":2,"ok":all(row["classification"] in ALLOWED_CLASSIFICATIONS for row in effects.values()),"result":result,"freeze_integrity":freezes,"legacy_shadow_systematic_defect":collision,"source_required_evidence_complete":all(row["evidence_for"] and all(item.get("provenance") for item in row["evidence_for"]) for row in effects.values() if row["classification"]=="SOURCE_REQUIRED"),"production_effect_mechanisms_added":0,"resolve_mutated":False,"later_non_caption_vfx_started":False}
    review_data={"schema":"video_cloner_step4d_review_data","schema_version":2,"selection_policy":"strongest_candidate_per_effect_plus_high_quality_negatives_and_high_contamination_ambiguities","cases":review}
    manifest={"schema":"video_cloner_step4d_review_manifest","schema_version":2,"result":result,"selection_policy":review_data["selection_policy"],"case_count":len(review),"cases":[{"identity":row["identity"],"roles":row["review_roles"]} for row in review],"human_review_required":True}
    artifacts={"step4d_existing_mechanism_inventory.json":json_bytes({"schema":"video_cloner_step4d_existing_mechanism_inventory","schema_version":2,"result":result,"mechanisms":mechanisms}),"step4d_effect_necessity_audit.json":json_bytes(audit),"step4d_necessity_investigation_validation.json":json_bytes(validation),"step4d_review_manifest.json":json_bytes(manifest),"step4d_review_data.json":json_bytes(review_data),"step4d_review_diagnostic.jpg":render(review,glyph_by)}
    artifacts["FINAL_REPORT.md"]=(f"RESULT: {result}\n\nSTATE\n- Four upstream freezes intact; 113 identities independently classified.\n- Effect-class counts are evidence-derived: {json.dumps(summary,sort_keys=True)}.\n- Legacy shadow heuristic remains unsafe and supplies no authority.\n\nCHANGED\n- Added read-only candidate-ranking investigation and one methodology test.\n\nVERIFIED\n- Review cases: {len(review)}; production effect mechanisms: 0.\n- Resolve untouched; Step 6 not started.\n\nNEXT\n- Human-review the strongest per-class candidates and adjudicate material necessity.\n\nRISK\n- Candidate scores are intentionally non-authoritative; no effect is source-required without human/source adjudication.\n").encode()
    return artifacts


def generate(output: Path) -> dict:
    if output.exists(): raise FileExistsError(output)
    first,second=build(),build()
    if first!=second: raise RuntimeError("non-deterministic investigation")
    output.mkdir(parents=True)
    for name,data in first.items(): (output/name).write_bytes(data)
    proof={"schema":"video_cloner_step4d_necessity_determinism","schema_version":2,"rerun_byte_identical":True,"artifact_sha256":{name:hashlib.sha256(data).hexdigest() for name,data in first.items()}}
    (output/"determinism_proof.json").write_bytes(json_bytes(proof))
    return {"output":str(output),"result":load(output/"step4d_effect_necessity_audit.json")["result"]}


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--output-dir",required=True,type=Path); args=parser.parse_args()
    print(json.dumps(generate(args.output_dir.resolve()),sort_keys=True)); return 0


if __name__=="__main__": raise SystemExit(main())

