#!/usr/bin/env python3
"""Build Major Step 3B.6A caption source-fidelity audit and reanalysis plan.

This step is intentionally read-only. It detects when a cue was positioned or
animated from a multi-word/group bounding box rather than from a cue-specific
word instance. It also emits the global caption-effect safety policy that later
Resolve patches must enforce.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

VERSION = "audit_caption_source_fidelity_step_3B_6A_v1_0_scene_instance_guard"
EXPECTED_V3_COUNT = 116
DIRECT_EXPECTED = 66
GROUP_EXPECTED = 50


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp.replace(path)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(value, encoding="utf-8", newline="\n")
    tmp.replace(path)


def canonical_hash(value: Dict[str, Any]) -> str:
    clean = dict(value)
    clean.pop("audit_hash", None)
    clean.pop("plan_hash", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def finite(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def normalize_text(value: Any) -> str:
    text = str(value or "").lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9']+", " ", text)
    return " ".join(text.split())


def words(value: Any) -> List[str]:
    text = normalize_text(value)
    return text.split() if text else []


def compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_text(value))


def similarity(a: Any, b: Any) -> float:
    aa, bb = compact(a), compact(b)
    if not aa or not bb:
        return 0.0
    return SequenceMatcher(None, aa, bb).ratio()


def bbox_from(value: Any) -> Optional[List[float]]:
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        nums = [finite(v) for v in value[:4]]
        if all(v is not None for v in nums):
            x1, y1, x2, y2 = [float(v) for v in nums]
            if x2 > x1 and y2 > y1:
                return [x1, y1, x2, y2]
    return None


def bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    denom = area_a + area_b - inter
    return inter / denom if denom > 0 else 0.0


def validate_gate(payload: Dict[str, Any], label: str, mode: str) -> List[str]:
    failures: List[str] = []
    if not payload.get("ok"):
        failures.append(f"{label}_not_ok")
    actual_mode = payload.get("mode", payload.get("run_mode"))
    if actual_mode != mode:
        failures.append(f"{label}_wrong_mode:{actual_mode}")
    if payload.get("failures"):
        failures.append(f"{label}_has_failures")
    return failures


def direct_event(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    resolution = row.get("profile_resolution") or {}
    details = resolution.get("details") or {}
    event = details.get("event") if isinstance(details, dict) else None
    return event if isinstance(event, dict) else None


def group_event(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    resolution = row.get("profile_resolution") or {}
    details = resolution.get("details") or {}
    group = details.get("group") if isinstance(details, dict) else None
    return group if isinstance(group, dict) else None


def observation_stats(cue_text: str, event: Dict[str, Any]) -> Dict[str, Any]:
    cue_words = words(cue_text)
    obs = [o for o in (event.get("observations") or []) if isinstance(o, dict)]
    observed_texts: List[str] = []
    exactish_count = 0
    contaminated_count = 0
    max_word_count = 0
    max_similarity = 0.0
    min_similarity = 1.0 if obs else 0.0
    bboxes: List[List[float]] = []
    frames: List[int] = []
    phrase_examples: List[str] = []

    for item in obs:
        text = str(item.get("text") or "")
        observed_texts.append(text)
        ow = words(text)
        sim = similarity(cue_text, text)
        max_word_count = max(max_word_count, len(ow))
        max_similarity = max(max_similarity, sim)
        min_similarity = min(min_similarity, sim)
        contains_cue = bool(compact(cue_text) and compact(cue_text) in compact(text))
        extra_words = max(0, len(ow) - max(1, len(cue_words)))
        if sim >= 0.82 and extra_words == 0:
            exactish_count += 1
        if extra_words > 0 or (not contains_cue and sim < 0.70):
            contaminated_count += 1
            if text and text not in phrase_examples:
                phrase_examples.append(text)
        bbox = bbox_from(item.get("normalized_bbox")) or bbox_from(item.get("bbox"))
        if bbox:
            bboxes.append(bbox)
        frame = item.get("frame_index")
        if isinstance(frame, int):
            frames.append(frame)

    return {
        "observation_count": len(obs),
        "observed_texts": observed_texts,
        "max_observed_word_count": max_word_count,
        "max_text_similarity": round(max_similarity, 6),
        "min_text_similarity": round(min_similarity, 6),
        "exactish_observation_count": exactish_count,
        "contaminated_observation_count": contaminated_count,
        "phrase_examples": phrase_examples[:5],
        "bboxes": bboxes,
        "frame_indices": sorted(set(frames)),
    }


def expected_aspect_limit(cue_text: str) -> float:
    # Deliberately permissive. Its purpose is to catch a single cue inheriting a
    # multi-word phrase box, not to judge typography exactly.
    chars = max(1, len(compact(cue_text)))
    return max(2.5, 0.92 * chars + 0.75)


def classify_row(row: Dict[str, Any]) -> Dict[str, Any]:
    cue_id = str(row.get("cue_id") or "")
    cue_text = str(row.get("rendered_text") or row.get("text") or "")
    event = direct_event(row)
    group = group_event(row)
    placement = (event or {}).get("placement") or {}
    typography = (event or {}).get("typography") or {}
    event_bbox = bbox_from(placement.get("normalized_bbox")) or bbox_from(placement.get("bbox"))
    pixel_bbox = bbox_from(placement.get("bbox"))
    font_height = finite(typography.get("font_height_px"))
    aspect = None
    if pixel_bbox and font_height:
        aspect = (pixel_bbox[2] - pixel_bbox[0]) / font_height
    elif pixel_bbox:
        width = pixel_bbox[2] - pixel_bbox[0]
        height = pixel_bbox[3] - pixel_bbox[1]
        aspect = width / height if height > 0 else None

    reasons: List[str] = []
    source_kind = "direct_event" if event else "classified_group" if group else "missing"
    stats: Dict[str, Any] = {}
    match_similarity = None

    if event:
        stats = observation_stats(cue_text, event)
        match_similarity = finite(((event.get("match") or {}).get("text_similarity")))
        if stats["observation_count"] == 0:
            reasons.append("no_source_observations")
        if stats["contaminated_observation_count"] > 0:
            reasons.append("multiword_or_wrong_text_observation")
        if stats["max_observed_word_count"] > max(1, len(words(cue_text))):
            reasons.append("observation_contains_more_words_than_cue")
        if match_similarity is not None and match_similarity < 0.72:
            reasons.append("low_event_text_similarity")
        if stats["max_text_similarity"] < 0.72:
            reasons.append("no_high_similarity_observation")
        if aspect is not None and aspect > expected_aspect_limit(cue_text):
            reasons.append("bbox_aspect_implausible_for_single_cue")
        clean = (
            stats["exactish_observation_count"] >= 1
            and stats["contaminated_observation_count"] == 0
            and (match_similarity is None or match_similarity >= 0.72)
            and (aspect is None or aspect <= expected_aspect_limit(cue_text))
        )
        if clean:
            exactness = "cue_instance_clean"
            next_action = "reuse_existing_dense_observations"
        else:
            exactness = "cue_instance_contaminated"
            next_action = "redetect_word_instance_from_source_frames"
    elif group:
        reasons.append("classified_group_is_not_a_cue_specific_instance")
        exactness = "group_inferred_not_source_exact"
        next_action = "redetect_word_instance_from_source_frames"
    else:
        reasons.append("missing_source_geometry")
        exactness = "missing_source_evidence"
        next_action = "redetect_word_instance_from_source_frames"

    animation = (event or {}).get("animation") or {}
    observation_count = int(stats.get("observation_count") or 0)
    if exactness == "cue_instance_clean" and observation_count >= 3:
        animation_evidence = "existing_observations_trackable"
    else:
        animation_evidence = "dense_frame_redetection_required"

    return {
        "name": str(row.get("name") or ""),
        "cue_id": cue_id,
        "cue_index": int(row.get("cue_index") or row.get("cue_number") or 0),
        "text": cue_text,
        "start": int(row.get("start") or 0),
        "end": int(row.get("end") or 0),
        "style_profile_id": str((row.get("profile_resolution") or {}).get("style_profile_id") or ""),
        "source_kind": source_kind,
        "source_event_id": (event or {}).get("event_id"),
        "source_group_frame": (group or {}).get("frame_index"),
        "source_match_similarity": round(match_similarity, 6) if match_similarity is not None else None,
        "source_bbox": event_bbox,
        "bbox_aspect_ratio": round(aspect, 6) if aspect is not None else None,
        "bbox_aspect_limit": round(expected_aspect_limit(cue_text), 6),
        "observation_stats": {k: v for k, v in stats.items() if k not in {"bboxes"}},
        "source_frame_indices": stats.get("frame_indices") or ([int(group.get("frame_index"))] if group and isinstance(group.get("frame_index"), int) else []),
        "source_observation_bboxes": stats.get("bboxes") or ([bbox_from(group.get("normalized_bbox"))] if group and bbox_from(group.get("normalized_bbox")) else []),
        "source_animation_detected": bool(animation.get("detected")),
        "source_animation_type": animation.get("type"),
        "source_animation_sample_count": int(animation.get("samples") or observation_count or 0),
        "geometry_exactness": exactness,
        "animation_evidence": animation_evidence,
        "reasons": sorted(set(reasons)),
        "next_action": next_action,
    }


def shared_bbox_links(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    links: List[Dict[str, Any]] = []
    observations: List[Tuple[str, int, List[float], str]] = []
    for item in items:
        for frame, bbox in zip(item.get("source_frame_indices") or [], item.get("source_observation_bboxes") or []):
            if isinstance(frame, int) and isinstance(bbox, list) and len(bbox) == 4:
                observations.append((item["cue_id"], frame, bbox, item["text"]))
    for i, (cue_a, frame_a, bbox_a, text_a) in enumerate(observations):
        for cue_b, frame_b, bbox_b, text_b in observations[i + 1 :]:
            if cue_a == cue_b or frame_a != frame_b:
                continue
            iou = bbox_iou(bbox_a, bbox_b)
            if iou >= 0.82:
                links.append({
                    "frame_index": frame_a,
                    "cue_a": cue_a,
                    "text_a": text_a,
                    "cue_b": cue_b,
                    "text_b": text_b,
                    "bbox_iou": round(iou, 6),
                })
    # Unique deterministic links.
    seen = set()
    unique = []
    for link in sorted(links, key=lambda x: (x["frame_index"], x["cue_a"], x["cue_b"])):
        key = (link["frame_index"], link["cue_a"], link["cue_b"])
        if key not in seen:
            seen.add(key)
            unique.append(link)
    return unique


def scene_components(items: List[Dict[str, Any]], links: List[Dict[str, Any]]) -> List[List[str]]:
    # Scene batches are intentionally bounded. Shared-box assignments are emitted
    # separately as evidence and must not chain the entire video into one scene.
    flagged = [item for item in items if item["geometry_exactness"] != "cue_instance_clean"]
    flagged.sort(key=lambda x: (x["start"], x["cue_index"]))
    batches: List[List[str]] = []
    current: List[Dict[str, Any]] = []
    scene_start: Optional[int] = None
    previous: Optional[Dict[str, Any]] = None
    for item in flagged:
        if not current:
            current = [item]
            scene_start = item["start"]
            previous = item
            continue
        close_to_previous = item["start"] - int(previous["end"]) <= 12
        within_scene_cap = item["end"] - int(scene_start or item["start"]) <= 48
        if close_to_previous and within_scene_cap:
            current.append(item)
        else:
            batches.append([member["cue_id"] for member in current])
            current = [item]
            scene_start = item["start"]
        previous = item
    if current:
        batches.append([member["cue_id"] for member in current])
    return batches


def build(args: argparse.Namespace) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    font_path = Path(args.font_report).resolve()
    position_plan_path = Path(args.position_plan).resolve()
    position_report_path = Path(args.position_idempotency_report).resolve()
    position_validation_path = Path(args.position_idempotency_validation).resolve()

    font = load_json(font_path)
    position_plan = load_json(position_plan_path)
    position_report = load_json(position_report_path)
    position_validation = load_json(position_validation_path)

    failures: List[str] = []
    warnings: List[str] = [
        "Step 3B.5B is technically valid but not a proof of source-exact geometry. Its source anchors can belong to multi-word OCR groups.",
        "Do not apply another full position or animation rollout until flagged cues are re-detected as individual word instances.",
        "Hard 100%-opacity blur-free outlines are forbidden by the emitted effect policy.",
    ]

    if not font.get("ok") or int(font.get("v3_candidate_count") or 0) != args.expected_v3_count:
        failures.append("font_report_gate_failed")
    if not position_plan.get("ok") or len(position_plan.get("items") or []) != args.expected_v3_count:
        failures.append("position_plan_gate_failed")
    failures.extend(validate_gate(position_report, "step_3B_5B_report", "idempotent_second_run"))
    failures.extend(validate_gate(position_validation, "step_3B_5B_validation", "idempotent_second_run"))

    rows = [row for row in (font.get("items") or []) if isinstance(row, dict)]
    items = [classify_row(row) for row in rows]
    items.sort(key=lambda row: (row["cue_index"], row["cue_id"]))
    if len(items) != args.expected_v3_count:
        failures.append(f"item_count_mismatch:{len(items)}")

    direct_count = sum(1 for row in items if row["source_kind"] == "direct_event")
    group_count = sum(1 for row in items if row["source_kind"] == "classified_group")
    clean_count = sum(1 for row in items if row["geometry_exactness"] == "cue_instance_clean")
    contaminated_count = sum(1 for row in items if row["geometry_exactness"] == "cue_instance_contaminated")
    group_inferred_count = sum(1 for row in items if row["geometry_exactness"] == "group_inferred_not_source_exact")
    missing_count = sum(1 for row in items if row["geometry_exactness"] == "missing_source_evidence")
    dense_required_count = sum(1 for row in items if row["next_action"] == "redetect_word_instance_from_source_frames")
    existing_trackable_count = sum(1 for row in items if row["animation_evidence"] == "existing_observations_trackable")

    links = shared_bbox_links(items)
    components = scene_components(items, links)
    item_map = {row["cue_id"]: row for row in items}
    scenes: List[Dict[str, Any]] = []
    for index, cues in enumerate(components, start=1):
        members = [item_map[cue] for cue in cues]
        scenes.append({
            "scene_id": f"caption_scene_{index:03d}",
            "cue_ids": cues,
            "texts": [m["text"] for m in members],
            "start_frame": min(m["start"] for m in members),
            "end_frame": max(m["end"] for m in members),
            "style_profile_ids": sorted({m["style_profile_id"] for m in members}),
            "reason_codes": sorted({reason for m in members for reason in m["reasons"]}),
            "required_action": "dense_word_instance_redetection",
        })

    # Explicit regression examples from the observed complex caption scene.
    example_expectations = {
        "sub_063": "the BACK",
        "sub_066": "at thei nand",
    }
    for cue_id, expected_phrase_fragment in example_expectations.items():
        row = item_map.get(cue_id)
        if not row:
            failures.append(f"missing_regression_example:{cue_id}")
            continue
        haystack = " ".join(row.get("observation_stats", {}).get("observed_texts") or []).lower()
        if expected_phrase_fragment.lower() not in haystack:
            warnings.append(f"Regression phrase changed for {cue_id}; inspect the current source report manually.")
        if row["geometry_exactness"] == "cue_instance_clean":
            failures.append(f"contamination_not_detected:{cue_id}")

    if direct_count != DIRECT_EXPECTED:
        warnings.append(f"Expected historical direct-event count {DIRECT_EXPECTED}, found {direct_count}.")
    if group_count != GROUP_EXPECTED:
        warnings.append(f"Expected historical classified-group count {GROUP_EXPECTED}, found {group_count}.")

    effect_policy = {
        "policy_version": "caption_effect_safety_policy_v1_0",
        "default_effect": "centered_shadow_glow",
        "hard_outline_default_forbidden": True,
        "solid_outline_100pct_no_blur_forbidden": True,
        "outline_requires_distinct_high_confidence_source_evidence": True,
        "outline_alpha_max": 0.75,
        "outline_must_be_accompanied_by_soft_shadow_or_glow": True,
        "shadow_or_glow_softness_min": 0.01,
        "shadow_or_glow_opacity_max": 0.85,
        "no_effect_when_source_has_no_supported_edge_effect": True,
        "notes": [
            "Text+ outline has no independent blur control; therefore a full-opacity hard outline is never an acceptable default.",
            "A distinct outline may be retained only with strong source evidence, reduced alpha, and a soft shadow/glow companion.",
        ],
    }

    summary = {
        "v3_item_count": len(items),
        "direct_event_source_count": direct_count,
        "classified_group_source_count": group_count,
        "cue_instance_clean_count": clean_count,
        "cue_instance_contaminated_count": contaminated_count,
        "group_inferred_not_source_exact_count": group_inferred_count,
        "missing_source_evidence_count": missing_count,
        "dense_word_instance_redetection_required_count": dense_required_count,
        "existing_observations_animation_trackable_count": existing_trackable_count,
        "shared_bbox_assignment_count": len(links),
        "flagged_scene_count": len(scenes),
        "current_position_plan_source_exact": False,
        "current_generic_animation_source_exact": False,
        "timeline_modified": False,
    }

    audit: Dict[str, Any] = {
        "ok": not failures,
        "step": "Major Step 3B.6A",
        "version": VERSION,
        "created_at_unix": time.time(),
        "font_report": str(font_path),
        "position_plan": str(position_plan_path),
        "position_idempotency_report": str(position_report_path),
        "position_idempotency_validation": str(position_validation_path),
        "summary": summary,
        "effect_policy": effect_policy,
        "shared_bbox_assignments": links,
        "items": items,
        "warnings": warnings,
        "failures": failures,
    }
    audit["audit_hash"] = canonical_hash(audit)

    plan: Dict[str, Any] = {
        "ok": not failures,
        "step": "Major Step 3B.6B input",
        "schema": "video_cloner_caption_scene_redetection_plan",
        "schema_version": "1.0",
        "created_at_unix": time.time(),
        "source_audit_hash": audit["audit_hash"],
        "source_video_relative_candidates": [
            "input/DZsqH7auhjt.mp4",
            "media/DZsqH7auhjt_proxy.mp4",
        ],
        "frame_rate": finite(font.get("timeline_fps"), 24.0),
        "required_output_contract": {
            "per_word_instance_bbox_per_source_frame": True,
            "per_word_opacity_proxy_per_source_frame": True,
            "per_word_scale_per_source_frame": True,
            "per_word_position_per_source_frame": True,
            "scene_membership_and_z_order": True,
            "confidence_and_fallback_reason": True,
        },
        "effect_policy": effect_policy,
        "scenes": scenes,
        "cue_targets": [
            {
                "cue_id": item["cue_id"],
                "cue_index": item["cue_index"],
                "text": item["text"],
                "start": item["start"],
                "end": item["end"],
                "style_profile_id": item["style_profile_id"],
                "existing_source_frame_indices": item["source_frame_indices"],
                "existing_source_event_id": item["source_event_id"],
                "existing_geometry_exactness": item["geometry_exactness"],
                "required_action": item["next_action"],
            }
            for item in items
            if item["next_action"] == "redetect_word_instance_from_source_frames"
        ],
        "warnings": warnings,
        "failures": failures,
    }
    plan["plan_hash"] = canonical_hash(plan)

    summary_text = "\n".join([
        "Video Cloner — Major Step 3B.6A source-fidelity audit",
        "",
        f"V3 captions: {len(items)}",
        f"Cue-specific clean source instances: {clean_count}",
        f"Contaminated direct events: {contaminated_count}",
        f"Group-inferred / not source-exact: {group_inferred_count}",
        f"Missing source evidence: {missing_count}",
        f"Dense word-instance re-detection required: {dense_required_count}",
        f"Existing observations sufficient for dense motion tracking: {existing_trackable_count}",
        f"Shared source-box assignments: {len(links)}",
        f"Flagged caption scenes: {len(scenes)}",
        "",
        "Decision:",
        "- Step 3B.5B is technically persistent/idempotent, but it is not source-exact.",
        "- Do not hide this under the general VFX layer. Caption scene geometry and motion need their own source-grounded model.",
        "- Next: Step 3B.6B dense word-instance re-detection on the original video.",
        "",
        "Permanent style guard:",
        "- Never default to a 100% opacity blur-free outline.",
        "- Default to centered soft shadow/glow when source evidence supports an edge effect.",
        "- Allow a distinct outline only with strong source evidence, reduced alpha, and a soft companion shadow/glow.",
        "",
        "Known contaminated examples:",
        "- sub_063 / back inherited the source box for 'the BACK'.",
        "- sub_066 / hand inherited the source box for the multi-word phrase 'at their hand'.",
    ]) + "\n"
    return audit, plan, summary_text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--font-report", required=True)
    parser.add_argument("--position-plan", required=True)
    parser.add_argument("--position-idempotency-report", required=True)
    parser.add_argument("--position-idempotency-validation", required=True)
    parser.add_argument("--audit-output", required=True)
    parser.add_argument("--redetection-plan-output", required=True)
    parser.add_argument("--summary-output", required=True)
    parser.add_argument("--expected-v3-count", type=int, default=EXPECTED_V3_COUNT)
    args = parser.parse_args()
    try:
        audit, plan, summary_text = build(args)
    except Exception as exc:
        audit = {
            "ok": False,
            "step": "Major Step 3B.6A",
            "version": VERSION,
            "failures": [f"audit_exception:{type(exc).__name__}:{exc}"],
        }
        plan = {
            "ok": False,
            "step": "Major Step 3B.6B input",
            "failures": audit["failures"],
        }
        summary_text = json.dumps(audit, ensure_ascii=False, indent=2) + "\n"
    audit_path = Path(args.audit_output).resolve()
    plan_path = Path(args.redetection_plan_output).resolve()
    summary_path = Path(args.summary_output).resolve()
    write_json(audit_path, audit)
    write_json(plan_path, plan)
    write_text(summary_path, summary_text)
    print(json.dumps({
        "ok": bool(audit.get("ok") and plan.get("ok")),
        "step": "Major Step 3B.6A",
        "version": VERSION,
        "summary": audit.get("summary"),
        "audit_output": str(audit_path),
        "redetection_plan_output": str(plan_path),
        "summary_output": str(summary_path),
        "warnings": audit.get("warnings") or [],
        "failures": audit.get("failures") or [],
    }, ensure_ascii=False, indent=2))
    return 0 if audit.get("ok") and plan.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
