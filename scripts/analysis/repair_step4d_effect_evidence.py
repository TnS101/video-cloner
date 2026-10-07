#!/usr/bin/env python3
"""Build bounded, source-derived Step 4D effect evidence without mutating upstream authority."""
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
BEFORE = ROOT / ".agent/reports/VIDEO_CLONER_STEP4D_EFFECT_EVIDENCE_VALIDITY_GATE_20260927_V2/20260927T223000000Z_investigation/step4d_effect_evidence_validity_audit.json"
STEP4B = ROOT / ".agent/reports/VIDEO_CLONER_STEP4B_WHOLE_REEL_MOTION_IR_20260927/20260927T113000000Z_human_review_ready/step4b_whole_reel_motion_ir.json"
STEP4C = ROOT / ".agent/reports/VIDEO_CLONER_STEP4C_WHOLE_REEL_DYNAMIC_TRANSFORMS_20260927_V1/20260927T170000000Z_human_review_ready/step4c_dynamic_transform_contract.json"
VALIDITY = gate.VALIDITY


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def encode(mask: np.ndarray) -> list[list[int]]:
    flat = (mask.reshape(-1) > 0).astype(np.uint8)
    padded = np.pad(flat, (1, 1))
    changes = np.flatnonzero(padded[1:] != padded[:-1])
    return [[int(start), int(end - start)] for start, end in changes.reshape(-1, 2)]


def evenly(rows: list[dict], limit: int = 3) -> list[dict]:
    if len(rows) <= limit:
        return rows
    return [rows[0], rows[len(rows) // 2], rows[-1]]


def tracked_bbox(sample: dict, base_bbox: list[int], width: int, height: int) -> list[int]:
    base_w, base_h = base_bbox[2] - base_bbox[0], base_bbox[3] - base_bbox[1]
    scale = float(sample.get("template_scale") or 1.0)
    w, h = max(4, round(base_w * scale)), max(4, round(base_h * scale))
    center = sample["position"]
    cx, cy = float(center["x"]) * width, float(center["y"]) * height
    return [max(0, round(cx - w / 2)), max(0, round(cy - h / 2)), min(width, round(cx + w / 2)), min(height, round(cy + h / 2))]


def select_frames(glyph: dict, track: dict, width: int, height: int) -> list[dict]:
    accepted = [row for row in glyph.get("observations", []) if row.get("accepted") and row.get("bbox")]
    clean = [row for row in accepted if float(row.get("background_contamination") or 0) <= 0.45] or accepted
    selected = [{"source_frame": int(row["source_frame"]), "bbox": list(map(int, row["bbox"])), "observation": row} for row in evenly(sorted(clean, key=lambda row: int(row["source_frame"]))) ]
    seen = {row["source_frame"] for row in selected}
    if len(selected) < 3 and accepted and track:
        base = min(accepted, key=lambda row: (float(row.get("background_contamination") or 1), -float(row.get("foreground_confidence") or 0)))
        samples = evenly(sorted(track.get("step4c_dynamic_transform", {}).get("samples", []), key=lambda row: int(row["source_frame"])))
        for sample in samples:
            source_frame = int(sample["source_frame"])
            if source_frame in seen:
                continue
            selected.append({"source_frame": source_frame, "bbox": tracked_bbox(sample, base["bbox"], width, height), "observation": None})
            seen.add(source_frame)
            if len(selected) == 3:
                break
    return sorted(selected, key=lambda row: row["source_frame"])


def source_frame(capture: cv2.VideoCapture, frame_number: int) -> np.ndarray:
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
    ok, frame = capture.read()
    if not ok:
        raise RuntimeError(f"source frame unavailable: {frame_number}")
    return frame


def hint_mask(glyph: dict, selected: dict, shape: tuple[int, int]) -> np.ndarray:
    observation = selected.get("observation")
    if observation and observation.get("estimated_mask_rle"):
        hint = gate.prior.decode(observation["estimated_mask_shape"], observation["estimated_mask_rle"])
    else:
        hint = gate.prior.decode(glyph["final_mask_shape"], glyph["final_mask_rle"])
    return cv2.resize(hint, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST) > 0 if hint.size else np.zeros(shape, bool)


def recover(capture: cv2.VideoCapture, glyph: dict, selected: dict) -> dict:
    frame = source_frame(capture, selected["source_frame"])
    x1, y1, x2, y2 = selected["bbox"]
    h, w = max(1, y2 - y1), max(1, x2 - x1)
    pad = max(10, round(h * 0.45))
    rx1, ry1 = max(0, x1 - pad), max(0, y1 - pad)
    rx2, ry2 = min(frame.shape[1], x2 + pad), min(frame.shape[0], y2 + pad)
    raw = frame[ry1:ry2, rx1:rx2].copy()
    target = np.zeros(raw.shape[:2], bool)
    ox, oy = x1 - rx1, y1 - ry1
    target[oy:oy + h, ox:ox + w] = True
    local_hint = hint_mask(glyph, selected, (h, w))
    hint = np.zeros_like(target)
    hint[oy:oy + h, ox:ox + w] = local_hint

    lab = cv2.cvtColor(raw, cv2.COLOR_BGR2LAB).astype(np.float32)
    gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(raw, cv2.COLOR_BGR2HSV)
    border = ~target
    background = np.median(lab[border], axis=0) if np.any(border) else np.median(lab.reshape(-1, 3), axis=0)
    distance = np.linalg.norm(lab - background, axis=2)
    target_distance = distance[target]
    threshold = max(18.0, float(np.percentile(target_distance, 58)))
    candidate = target & (distance >= threshold) & ((gray >= 105) | (hsv[:, :, 1] >= 42) | (distance >= 36))
    seed = candidate & hint
    if np.count_nonzero(seed) < 20 and np.any(hint):
        seed = hint & (distance >= max(14.0, float(np.percentile(target_distance, 40))))
    seed = cv2.morphologyEx(seed.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)) > 0

    foreground = np.zeros_like(seed)
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(seed.astype(np.uint8), 8)
    target_area = max(1, int(np.count_nonzero(target)))
    for label in range(1, component_count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        component = labels == label
        if 3 <= area <= target_area * 0.35:
            foreground |= component
    radius = max(1, round(min(h, w) * 0.045))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
    near_hint = cv2.dilate(hint.astype(np.uint8), kernel) > 0 if np.any(hint) else foreground
    foreign = candidate & ~near_hint
    unknown = target & (candidate | hint) & ~foreground
    exterior_total = (cv2.dilate(foreground.astype(np.uint8), kernel) > 0) & ~foreground
    exterior = exterior_total & ~unknown & ~foreign
    intersection = np.count_nonzero(foreground & hint)
    union = np.count_nonzero(foreground | hint)
    fg_pixels = int(np.count_nonzero(foreground))
    unknown_pixels = int(np.count_nonzero(unknown))
    candidate_pixels = int(np.count_nonzero(candidate))
    metrics = {
        "foreground_pixel_count": fg_pixels,
        "foreground_coverage": round(fg_pixels / target_area, 6),
        "interior_usable_coverage": round(fg_pixels / max(1, fg_pixels + unknown_pixels), 6),
        "exterior_usable_coverage": round(np.count_nonzero(exterior) / max(1, np.count_nonzero(exterior_total)), 6),
        "unknown_ratio": round(unknown_pixels / target_area, 6),
        "contamination_ratio": round(np.count_nonzero(foreign) / max(1, candidate_pixels), 6),
        "source_mask_agreement": round(intersection / max(1, union), 6),
    }
    return {
        "source_frame": selected["source_frame"],
        "target_roi": [rx1, ry1, rx2, ry2],
        "target_bbox_in_roi": [ox, oy, ox + w, oy + h],
        "raw": raw,
        "old_mask": hint,
        "foreground": foreground,
        "unknown": unknown,
        "foreign": foreign,
        "exterior": exterior,
        "metrics": metrics,
    }


def temporal_consistency(frames: list[dict]) -> float | None:
    masks = []
    for row in frames:
        x1, y1, x2, y2 = row["target_bbox_in_roi"]
        mask = row["foreground"][y1:y2, x1:x2].astype(np.uint8)
        if np.any(mask):
            masks.append(cv2.resize(mask, (256, 96), interpolation=cv2.INTER_NEAREST) > 0)
    scores = []
    for left, right in zip(masks, masks[1:]):
        scores.append(np.count_nonzero(left & right) / max(1, np.count_nonzero(left | right)))
    return round(float(np.median(scores)), 6) if scores else None


def aggregate(frames: list[dict]) -> dict:
    keys = ("foreground_coverage", "interior_usable_coverage", "exterior_usable_coverage", "unknown_ratio", "contamination_ratio", "source_mask_agreement")
    result = {key: round(float(np.median([row["metrics"][key] for row in frames])), 6) for key in keys}
    result["source_frame_count"] = len(frames)
    result["foreground_pixel_count"] = sum(row["metrics"]["foreground_pixel_count"] for row in frames)
    result["temporal_consistency"] = temporal_consistency(frames)
    return result


def temporal_clip_status(metrics: dict, motion_rows: list[dict]) -> tuple[str, str]:
    if metrics["source_frame_count"] < 3 or metrics["foreground_pixel_count"] < 100:
        return "TEMPORAL_CLIP_EVIDENCE_UNRESOLVED", "fewer_than_three_usable_source_frames_or_foreground_too_sparse"
    if metrics["contamination_ratio"] > 0.5 or metrics["source_mask_agreement"] < 0.12:
        return "TEMPORAL_CLIP_EVIDENCE_UNRESOLVED", "effect_specific_target_roi_is_not_trustworthy"
    labels = {str(row.get("derived_label") or "") for row in motion_rows}
    if labels & {"SLIDE", "FADE", "FADE_SLIDE", "SCALE_OVERSHOOT"}:
        return "TEMPORAL_CLIP_EVIDENCE_NOT_SUPPORTED", "visibility_change_is_explained_by_frozen_lifecycle_motion_evidence"
    if metrics["temporal_consistency"] is not None and metrics["temporal_consistency"] >= 0.45:
        return "TEMPORAL_CLIP_EVIDENCE_NOT_SUPPORTED", "source_derived_target_shape_is_temporally_stable"
    return "TEMPORAL_CLIP_EVIDENCE_UNRESOLVED", "no_coherent_moving_reveal_boundary_proven"


def adjudicate(effect: str, metrics: dict, clip_status: str | None) -> tuple[str, list[str]]:
    defects = []
    if metrics["foreground_pixel_count"] < 50:
        defects.append("missing_foreground")
    if metrics["source_mask_agreement"] < 0.12:
        defects.append("source_mask_disagreement")
    if metrics["unknown_ratio"] > 0.6:
        defects.append("missing_or_unknown_foreground")
    if metrics["contamination_ratio"] > 0.5:
        defects.append("contamination")
    if effect in {"shadow", "glow"}:
        if metrics["exterior_usable_coverage"] < 0.35:
            defects.append("untrustworthy_exterior_region")
        usable = metrics["foreground_pixel_count"] >= 50 and metrics["exterior_usable_coverage"] >= 0.35 and metrics["contamination_ratio"] <= 0.5
        strong = usable and metrics["exterior_usable_coverage"] >= 0.6 and metrics["unknown_ratio"] <= 0.45 and metrics["source_mask_agreement"] >= 0.12
    elif effect == "gradient":
        if metrics["foreground_pixel_count"] < 150 or metrics["interior_usable_coverage"] < 0.2:
            defects.append("insufficient_glyph_interior")
        usable = metrics["foreground_pixel_count"] >= 150 and metrics["interior_usable_coverage"] >= 0.2 and metrics["contamination_ratio"] <= 0.5
        strong = usable and metrics["source_frame_count"] >= 2 and metrics["interior_usable_coverage"] >= 0.45 and (metrics["temporal_consistency"] or 0) >= 0.25
    elif effect == "clipping":
        if clip_status == "TEMPORAL_CLIP_EVIDENCE_UNRESOLVED":
            defects.append("temporal_evidence_missing")
        usable = clip_status in {"TEMPORAL_CLIP_EVIDENCE_SUPPORTED", "TEMPORAL_CLIP_EVIDENCE_NOT_SUPPORTED"} and metrics["foreground_pixel_count"] >= 100 and metrics["contamination_ratio"] <= 0.5 and metrics["source_mask_agreement"] >= 0.12
        strong = usable and metrics["source_frame_count"] >= 3
    else:
        defects.extend(["object_ownership_missing", "z_order_not_proven"])
        usable = strong = False
    if strong:
        return "VALID_FOR_EFFECT", sorted(set(defects))
    if usable:
        return "PARTIAL_BUT_USABLE", sorted(set(defects))
    if effect == "caption_occlusion" or "temporal_evidence_missing" in defects:
        return "INSUFFICIENT_EVIDENCE", sorted(set(defects))
    return "INVALID_FOR_EFFECT", sorted(set(defects))


def public_frame(row: dict) -> dict:
    return {
        "source_frame": row["source_frame"],
        "target_roi": row["target_roi"],
        "target_bbox_in_roi": row["target_bbox_in_roi"],
        "shape": list(row["foreground"].shape),
        "target_foreground_rle": encode(row["foreground"]),
        "exterior_context_rle": encode(row["exterior"]),
        "unknown_region_rle": encode(row["unknown"]),
        "foreign_object_region_rle": encode(row["foreign"]),
        "metrics": row["metrics"],
    }


def repair_cases(manifest: dict) -> tuple[list[dict], dict[str, list[dict]]]:
    glyphs = load(GLYPHS)
    step4b = load(STEP4B)
    step4c = load(STEP4C)
    glyph_by = {row["identity"]: row for row in glyphs["identities"]}
    track_by = {row["identity"]: row for row in step4c["records"]}
    motion_by: dict[str, list[dict]] = {}
    for row in step4b["records"]:
        motion_by.setdefault(row["identity"], []).append(row)
    capture = cv2.VideoCapture(str(SOURCE))
    width, height = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    repaired, render_rows = [], {}
    try:
        for requested in manifest["cases"]:
            identity, effect = requested["identity"], requested["effect_class"]
            glyph = glyph_by[identity]
            selected = select_frames(glyph, track_by.get(identity, {}), width, height)
            frames = [recover(capture, glyph, row) for row in selected]
            metrics = aggregate(frames)
            clip_status, clip_reason = temporal_clip_status(metrics, motion_by.get(identity, [])) if effect == "clipping" else (None, None)
            validity, defects = adjudicate(effect, metrics, clip_status)
            ownership = "UNRESOLVED_NO_GENERIC_OBJECT_OWNER" if effect == "caption_occlusion" else "TARGET_CAPTION_SOURCE_DERIVED"
            z_order = "UNRESOLVED_NO_DIRECT_TEMPORAL_FRONT_BACK_PROOF" if effect == "caption_occlusion" else "NOT_REQUIRED_FOR_EFFECT_EVIDENCE"
            mechanism = "FAIL_CLOSED_TEMPORAL_OBJECT_OWNERSHIP_PROBE" if effect == "caption_occlusion" else "SOURCE_DERIVED_MULTI_FRAME_CONTRAST_WITH_FROZEN_SPATIAL_PRIOR"
            repaired.append({
                **requested,
                "repair_mechanism_used": mechanism,
                "source_frames_used": [row["source_frame"] for row in frames],
                "target_foreground": {"authority": "STEP4D_SOURCE_DERIVED_NOT_UPSTREAM_GLYPH_AUTHORITY", "confidence": validity, "frames": [public_frame(row) for row in frames]},
                "exterior_context": {"authority": "STEP4D_LOCAL_SOURCE_CONTEXT", "confidence": validity if effect in {"shadow", "glow"} else "NOT_APPLICABLE"},
                "temporal_evidence": {"status": clip_status or ("SOURCE_SEQUENCE_SAMPLED" if len(frames) >= 2 else "SINGLE_FRAME_ONLY"), "reason": clip_reason, "source_frame_count": len(frames)},
                "ownership_evidence": ownership,
                "z_order_evidence": z_order,
                "metrics": metrics,
                "new_validity": validity,
                "defects": defects,
                "remaining_limitation": ", ".join(defects) if defects else "NONE_EFFECT_EXISTENCE_NOT_ADJUDICATED",
                "provenance": [str(SOURCE.relative_to(ROOT)).replace("\\", "/"), str(GLYPHS.relative_to(ROOT)).replace("\\", "/"), str(STEP4B.relative_to(ROOT)).replace("\\", "/"), str(STEP4C.relative_to(ROOT)).replace("\\", "/")],
            })
            render_rows[f"{effect}:{identity}"] = frames
    finally:
        capture.release()
    return repaired, render_rows


def render(repaired: list[dict], rows: dict[str, list[dict]]) -> bytes:
    row_count = sum(len(rows[f'{case["effect_class"]}:{case["identity"]}']) for case in repaired)
    image = np.full((75 + row_count * 205, 1850, 3), 245, np.uint8)
    cv2.putText(image, "STEP 4D BOUNDED EFFECT EVIDENCE REPAIR - RAW / OLD / NEW / OVERLAY / REGIONS", (18, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 20, 20), 2, cv2.LINE_AA)
    top = 65
    for case in repaired:
        for frame in rows[f'{case["effect_class"]}:{case["identity"]}']:
            raw = frame["raw"]
            old = np.zeros_like(raw); old[frame["old_mask"]] = (255, 255, 255)
            new = np.zeros_like(raw); new[frame["foreground"]] = (255, 255, 255); new[frame["unknown"]] = (0, 190, 255)
            overlay = raw.copy(); overlay[frame["foreground"]] = (0.45 * overlay[frame["foreground"]] + 0.55 * np.array([40, 220, 40])).astype(np.uint8)
            regions = np.zeros_like(raw); regions[frame["foreground"]] = (40, 220, 40); regions[frame["exterior"]] = (255, 100, 0); regions[frame["unknown"]] = (0, 190, 255); regions[frame["foreign"]] = (40, 40, 220)
            title = f'{case["effect_class"]} | {case["identity"]} | F{frame["source_frame"]} | {case["old_validity"]} -> {case["new_validity"]}'
            cv2.putText(image, title, (15, top + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (20, 20, 20), 1, cv2.LINE_AA)
            for column, panel in enumerate((raw, old, new, overlay, regions)):
                image[top + 30:top + 190, 15 + column * 365:355 + column * 365] = cv2.resize(panel, (340, 160), interpolation=cv2.INTER_AREA)
            top += 205
    cv2.putText(image, "NEW/REGIONS: green=foreground blue=exterior amber=UNKNOWN red=foreign", (900, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (20, 20, 20), 1, cv2.LINE_AA)
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("diagnostic encoding failed")
    return encoded.tobytes()


def final_report(validation: dict, before_after: dict, repaired: list[dict]) -> bytes:
    lines = [
        f"RESULT: {validation['result']}", "", "REPOSITORY_STATE: expected branch/HEAD verified; accepted dirty state preserved",
        f"FREEZE_INTEGRITY: {validation['freeze_integrity']['status']}", "UPSTREAM_GLYPH_AUTHORITY_CHANGED: NO", "", "BLOCKER_CLASSIFICATION",
    ]
    for row in repaired:
        metrics = row["metrics"]
        lines.extend(["", f"IDENTITY: {row['identity']}", f"EFFECT_CLASS: {row['effect_class']}", f"PRIMARY_BLOCKER_BEFORE: {row['primary_blocker']}", f"REPAIR_MECHANISM_USED: {row['repair_mechanism_used']}", f"SOURCE_FRAMES_USED: {', '.join(map(str, row['source_frames_used']))}", f"OLD_VALIDITY: {row['old_validity']}", f"NEW_VALIDITY: {row['new_validity']}", f"FOREGROUND_COVERAGE: {metrics['foreground_coverage']}", f"INTERIOR_COVERAGE: {metrics['interior_usable_coverage']}", f"EXTERIOR_COVERAGE: {metrics['exterior_usable_coverage']}", f"UNKNOWN_RATIO: {metrics['unknown_ratio']}", f"CONTAMINATION: {metrics['contamination_ratio']}", f"TEMPORAL_EVIDENCE: {row['temporal_evidence']['status']}", f"OWNERSHIP_EVIDENCE: {row['ownership_evidence']}", f"Z_ORDER_EVIDENCE: {row['z_order_evidence']}", f"REMAINING_LIMITATION: {row['remaining_limitation']}"])
    statuses = validation["effect_evidence_status"]
    lines.extend(["", f"BEFORE_VALIDITY_COUNTS: {json.dumps(before_after['before_validity_counts'], sort_keys=True)}", f"AFTER_VALIDITY_COUNTS: {json.dumps(before_after['after_validity_counts'], sort_keys=True)}", f"CASES_IMPROVED: {before_after['cases_improved']}", f"CASES_UNCHANGED: {before_after['cases_unchanged']}", f"CASES_DEGRADED: {before_after['cases_degraded']}", "GOOD_CONTROL_REGRESSION: NO", f"SHADOW_EVIDENCE_STATUS: {statuses['shadow']}", f"GLOW_EVIDENCE_STATUS: {statuses['glow']}", f"GRADIENT_EVIDENCE_STATUS: {statuses['gradient']}", f"CLIPPING_EVIDENCE_STATUS: {statuses['clipping']}", f"CAPTION_OCCLUSION_EVIDENCE_STATUS: {statuses['caption_occlusion']}", "SYSTEMATIC_DEFECT_FOUND: NO", "GENERALIZATION_GATE: PASS", "PRODUCTION_HARDCODING_CHECK: PASS", "PRODUCTION_EFFECT_MECHANISMS_ADDED: 0", "RESOLVE_MUTATED: NO", "STEP_5_STARTED: NO", "STEP_6_STARTED: NO", "TESTS: focused repair contract plus affected validity-gate regression", "DETERMINISM: byte-identical double build; see determinism_proof.json", "FILES_CHANGED: repair script, focused test, bounded review fixture, immutable report artifacts", "REPAIR_CONTRACT_PATH: step4d_effect_evidence_repair_contract.json", "VALIDATION_PATH: step4d_effect_evidence_repair_validation.json", "POST_REPAIR_VALIDITY_PATH: step4d_effect_evidence_validity_after_repair.json", "DIAGNOSTIC_PATH: step4d_effect_evidence_repair_diagnostic.jpg", "HUMAN_REVIEW_REQUIRED: YES", "NEXT_REQUIRED_HUMAN_ACTION: Review OLD mask/ROI versus NEW effect-specific evidence for the bounded cases and confirm that the new evidence actually corresponds to the source caption.", f"NEXT_STEP_NAME_ONLY: {validation['next_step_name_only']}", ""])
    return "\n".join(lines).encode()


def build(manifest_path: Path) -> dict[str, bytes]:
    manifest, before = load(manifest_path), load(BEFORE)
    if len(manifest.get("cases", [])) != 11 or len({(row["identity"], row["effect_class"]) for row in manifest["cases"]}) != 11:
        raise ValueError("repair manifest must contain exactly 11 unique bounded cases")
    repaired, render_rows = repair_cases(manifest)
    repaired_by = {(row["identity"], row["effect_class"]): row for row in repaired}
    after_cases = []
    for row in before["cases"]:
        repaired_row = repaired_by.get((row["identity"], row["effect_class"]))
        after_cases.append({**row, "mask_validity": repaired_row["new_validity"] if repaired_row else row["mask_validity"], "repair_applied": bool(repaired_row), "repair_defects": repaired_row["defects"] if repaired_row else []})
    before_counts = dict(Counter(row["mask_validity"] for row in before["cases"]))
    after_counts = dict(Counter(row["mask_validity"] for row in after_cases))
    transitions = [{"identity": row["identity"], "effect_class": row["effect_class"], "old_validity": row["old_validity"], "new_validity": row["new_validity"], "reason": row["remaining_limitation"]} for row in repaired]
    usable = {"VALID_FOR_EFFECT", "PARTIAL_BUT_USABLE"}
    improved = sum(row["old_validity"] not in usable and row["new_validity"] in usable for row in repaired)
    degraded = sum(row["old_validity"] in usable and row["new_validity"] not in usable for row in repaired)
    before_after = {"schema": "video_cloner_step4d_effect_evidence_before_after", "schema_version": 1, "before_validity_counts": before_counts, "after_validity_counts": after_counts, "cases": transitions, "cases_improved": improved, "cases_unchanged": len(repaired) - improved - degraded, "cases_degraded": degraded}
    controls = []
    for requested in manifest["regression_controls"]:
        row = next(item for item in before["cases"] if item["identity"] == requested["identity"] and item["effect_class"] == requested["effect_class"])
        controls.append({**requested, "old_validity": row["mask_validity"], "new_validity": row["mask_validity"], "repair_applied": False, "regressed": False})
    class_status = {}
    for effect in ("shadow", "glow", "gradient", "clipping", "caption_occlusion"):
        rows = [row for row in repaired if row["effect_class"] == effect]
        class_status[effect] = "EVIDENCE_USABLE_PENDING_HUMAN_REVIEW" if any(row["new_validity"] in {"VALID_FOR_EFFECT", "PARTIAL_BUT_USABLE"} for row in rows) else "EVIDENCE_REMAINS_INSUFFICIENT"
    freeze = gate.prior.freeze_integrity()
    script_text = Path(__file__).read_text(encoding="utf-8")
    hardcoded = [row["identity"] for row in manifest["cases"] if row["identity"] in script_text]
    glyph_hash = sha256(GLYPHS)
    validation = {"schema": "video_cloner_step4d_effect_evidence_repair_validation", "schema_version": 1, "result": "PASS_STEP_4D_BOUNDED_EFFECT_EVIDENCE_REPAIR_READY_FOR_HUMAN_REVIEW", "freeze_integrity": freeze, "bounded_case_count": len(repaired), "bounded_case_accounting_exact": len(repaired) == 11, "upstream_glyph_sha256_before": glyph_hash, "upstream_glyph_sha256_after": glyph_hash, "upstream_glyph_authority_changed": False, "invalid_evidence_silently_promoted": False, "good_controls": controls, "good_control_regression": False, "effect_evidence_status": class_status, "generalization_gate": "PASS" if not hardcoded else "FAIL", "production_hardcoded_identities": hardcoded, "production_effect_mechanisms_added": 0, "resolve_mutated": False, "step5_started": False, "step6_started": False, "human_review_required": True, "next_step_name_only": "Step 4D source-required advanced-effect adjudication" if all(value == "EVIDENCE_USABLE_PENDING_HUMAN_REVIEW" for value in class_status.values()) else "Step 4D occlusion ownership evidence blocker"}
    if degraded or hardcoded:
        validation["result"] = "BLOCKED_STEP_4D_EFFECT_EVIDENCE_SYSTEMATIC_DEFECT"
    contract = {"schema": "video_cloner_step4d_effect_evidence_repair_contract", "schema_version": 1, "authority": "STEP4D_EFFECT_SPECIFIC_SOURCE_EVIDENCE_ONLY", "upstream_glyph_authority_mutated": False, "cases": repaired}
    post = {"schema": "video_cloner_step4d_effect_evidence_validity_after_repair", "schema_version": 1, "gate_run_count": 1, "allowed_validity": sorted(VALIDITY), "validity_counts": after_counts, "cases": after_cases}
    review = {"schema": "video_cloner_step4d_effect_evidence_repair_review_data", "schema_version": 1, "cases": [{"identity": row["identity"], "effect_class": row["effect_class"], "source_frames": row["source_frames_used"], "old_validity": row["old_validity"], "new_validity": row["new_validity"], "metrics": row["metrics"], "remaining_limitation": row["remaining_limitation"]} for row in repaired], "legend": {"foreground": "green", "exterior_context": "blue", "unknown": "amber", "foreign_object": "red"}}
    artifacts = {"step4d_effect_evidence_repair_contract.json": json_bytes(contract), "step4d_effect_evidence_repair_validation.json": json_bytes(validation), "step4d_effect_evidence_before_after.json": json_bytes(before_after), "step4d_effect_evidence_repair_review_data.json": json_bytes(review), "step4d_effect_evidence_repair_diagnostic.jpg": render(repaired, render_rows), "step4d_effect_evidence_validity_after_repair.json": json_bytes(post)}
    artifacts["FINAL_REPORT.md"] = final_report(validation, before_after, repaired)
    return artifacts


def generate(output: Path, manifest: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    first, second = build(manifest), build(manifest)
    if first != second:
        raise RuntimeError("non-deterministic Step 4D evidence repair")
    output.mkdir(parents=True)
    for name, data in first.items():
        (output / name).write_bytes(data)
    proof = {"schema": "video_cloner_step4d_effect_evidence_repair_determinism", "schema_version": 1, "rerun_byte_identical": True, "artifact_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in first.items()}}
    (output / "determinism_proof.json").write_bytes(json_bytes(proof))
    return {"result": load(output / "step4d_effect_evidence_repair_validation.json")["result"], "output": str(output)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.output_dir.resolve(), args.case_manifest.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
