#!/usr/bin/env python3
"""Classify the remaining unresolved caption rows using accepted source evidence.

Offline-only. Resolve is never touched.

This stage intentionally does not turn negative OCR into source absence. It adds
three conservative evidence classes on top of the accepted unresolved-layer
recovery artifact:

1. exact source OCR anchor + source-pixel temporal continuity;
2. exact source OCR anchor with identity proven but duration still unresolved;
3. structural membership in an already accepted exact adjacent compound OCR
   decomposition.

A source-not-materialized claim is allowed only through an explicit multi-signal
absence gate. The accepted input does not provide the required full-window
semantic scan/component audit, so rows that cannot be positively recovered stay
unresolved instead of being deleted by inference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

import cv2
import numpy as np

TASK_ID = "DZSQH7AUHJT_STEP_3E_UNRESOLVED_SOURCE_CLASSIFICATION_V1"
RECOVERY = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_VISUAL_LAYER_RECOVERY_V1/unresolved_visual_layer_recovery_v1.json")
RECOVERY_VALIDATION = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_VISUAL_LAYER_RECOVERY_V1/unresolved_visual_layer_recovery_validation.json")
VF = Path("artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_AUTHORITY_V2/visual_fidelity_authority_v2.json")
DEFAULT_OUTPUT = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_SOURCE_CLASSIFICATION_V1/unresolved_source_classification_v1.json")

EXPECTED_RECOVERY_SHA256 = "bb4fab45389dbb10d58970955c6194e3f4d8e7351d79f397074bfb15b2fb8e5d"
EXPECTED_RECOVERY_VALIDATION_SHA256 = "7339bf038feafce8eaefdf3702e1457e67a7fcbc034a34eddf7183b2f7a6b1c7"
EXPECTED_VF_SHA256 = "6f7cdf265dcb18611e7f6326d7d12de7a3dade7b2a7b6d33e1d406d5645ca6f5"
EXPECTED_SOURCE_SHA256 = "fd60f596fb09031d8fa41071691cbdc1884edb32fd79f436f6be1df1ca186635"

EXPECTED_RECOVERY_EVALUATED = 23
EXPECTED_PRIOR_COMPANION_RECOVERED = 1
EXPECTED_REMAINING = 22
EXPECTED_STRUCTURAL = 117
EXPECTED_PHYSICAL = 114
TIMELINE_FPS = 24.0
REF_WIDTH = 540
REF_HEIGHT = 960

EXACT_LONG_MIN_CONFIDENCE = 0.90
EXACT_SHORT_MIN_CONFIDENCE = 0.95
TRACK_STRONG_SCORE = 0.78
TRACK_LONG_MIN_SUPPORT = 3
TRACK_SHORT_MIN_SUPPORT = 2
TRACK_RADIUS_FRAMES = 5


class BuildError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise BuildError(code)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def compact_text(value: Any) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def normalized_path(value: Any) -> Path:
    return Path(str(value or "").replace("\\", "/"))


def median(values: Sequence[float], default: float = 0.0) -> float:
    return float(statistics.median(values)) if values else float(default)


def source_video_from_vf(repo_root: Path, vf: Mapping[str, Any]) -> Path:
    for _, row in (vf.get("inputs") or {}).items():
        if not isinstance(row, Mapping):
            continue
        path_value = str(row.get("path") or "")
        if path_value.replace("\\", "/").endswith("DZsqH7auhjt.mp4"):
            path = repo_root / normalized_path(path_value)
            require(path.is_file(), f"source_video:{path}")
            return path
    fallback = repo_root / "input" / "DZsqH7auhjt.mp4"
    require(fallback.is_file(), f"source_video:{fallback}")
    return fallback


def verify_inputs(repo_root: Path, recovery: Mapping[str, Any], validation: Mapping[str, Any], vf: Mapping[str, Any]) -> Path:
    require(sha256(repo_root / RECOVERY) == EXPECTED_RECOVERY_SHA256, "recovery_sha256")
    require(sha256(repo_root / RECOVERY_VALIDATION) == EXPECTED_RECOVERY_VALIDATION_SHA256, "recovery_validation_sha256")
    require(sha256(repo_root / VF) == EXPECTED_VF_SHA256, "vf_sha256")
    require(recovery.get("ok") is True, "recovery_ok")
    require(validation.get("ok") is True, "recovery_validation_ok")
    require(vf.get("ok") is True, "vf_ok")
    require((recovery.get("policy") or {}).get("negative_ocr_promoted_to_absence") is False, "prior_negative_absence")
    require((recovery.get("policy") or {}).get("geometry_only_semantic_promotion") is False, "prior_geometry_promotion")
    summary = recovery.get("summary") or {}
    require(int(summary.get("evaluated_unresolved") or 0) == EXPECTED_RECOVERY_EVALUATED, "recovery_evaluated")
    require(int(summary.get("source_visual_companion_recovered") or 0) == EXPECTED_PRIOR_COMPANION_RECOVERED, "recovery_companion")
    require(int(summary.get("source_unresolved_after_recovery") or 0) == EXPECTED_REMAINING, "recovery_remaining")
    source = source_video_from_vf(repo_root, vf)
    require(sha256(source) == EXPECTED_SOURCE_SHA256, "source_video_sha256")
    return source


def bbox_ref_from_normalized(value: Sequence[float]) -> list[int]:
    require(isinstance(value, Sequence) and len(value) == 4, "normalized_bbox")
    x0, y0, x1, y1 = [float(v) for v in value]
    box = [
        int(round(x0 * REF_WIDTH)),
        int(round(y0 * REF_HEIGHT)),
        int(round(x1 * REF_WIDTH)),
        int(round(y1 * REF_HEIGHT)),
    ]
    box[0] = max(0, min(REF_WIDTH - 1, box[0]))
    box[1] = max(0, min(REF_HEIGHT - 1, box[1]))
    box[2] = max(box[0] + 1, min(REF_WIDTH, box[2]))
    box[3] = max(box[1] + 1, min(REF_HEIGHT, box[3]))
    return box


class VideoSource:
    def __init__(self, path: Path):
        self.cap = cv2.VideoCapture(str(path))
        require(self.cap.isOpened(), f"video_open:{path}")
        self.fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.count = int(round(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
        require(self.fps > 0 and self.count > 0, "video_meta")

    def read_ref(self, timeline_frame: int) -> np.ndarray:
        source_frame = max(0, min(self.count - 1, int(round(int(timeline_frame) * self.fps / TIMELINE_FPS))))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, source_frame)
        ok, frame = self.cap.read()
        require(ok and frame is not None, f"video_frame:{timeline_frame}")
        if frame.shape[1] == REF_WIDTH and frame.shape[0] == REF_HEIGHT:
            return frame
        return cv2.resize(frame, (REF_WIDTH, REF_HEIGHT), interpolation=cv2.INTER_AREA)

    def close(self) -> None:
        self.cap.release()


def highpass(gray: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(gray, (0, 0), 2.0)
    value = cv2.absdiff(gray, blur)
    return cv2.normalize(value, None, 0, 255, cv2.NORM_MINMAX)


def exact_anchor_candidates(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    canonical = compact_text(row.get("canonical_text"))
    threshold = EXACT_SHORT_MIN_CONFIDENCE if len(canonical) <= 3 else EXACT_LONG_MIN_CONFIDENCE
    result = []
    for candidate in row.get("high_confidence_ocr_candidates") or []:
        if not isinstance(candidate, Mapping):
            continue
        confidence = float(candidate.get("confidence") or 0.0)
        if confidence < threshold:
            continue
        if compact_text(candidate.get("text")) != canonical:
            continue
        box = candidate.get("normalized_bbox")
        if not isinstance(box, list) or len(box) != 4:
            continue
        item = dict(candidate)
        item["confidence"] = round(confidence, 6)
        result.append(item)
    result.sort(key=lambda x: (float(x.get("confidence") or 0.0), -int(x.get("timeline_frame") or 0)), reverse=True)
    return result


def strongest_consecutive_run_containing_anchor(rows: Sequence[Mapping[str, Any]], anchor_frame: int, threshold: float) -> list[dict[str, Any]]:
    accepted = sorted((dict(row) for row in rows if float(row.get("score") or -1.0) >= threshold), key=lambda r: int(r["timeline_frame"]))
    runs: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for row in accepted:
        frame = int(row["timeline_frame"])
        if current and frame != int(current[-1]["timeline_frame"]) + 1:
            runs.append(current)
            current = []
        current.append(row)
    if current:
        runs.append(current)
    containing = [run for run in runs if any(int(x["timeline_frame"]) == int(anchor_frame) for x in run)]
    if not containing:
        return []
    containing.sort(key=lambda run: (len(run), max(float(x.get("score") or 0.0) for x in run)), reverse=True)
    return containing[0]


def track_exact_anchor(video: VideoSource, anchor: Mapping[str, Any], search_window: Sequence[int]) -> dict[str, Any]:
    anchor_frame = int(anchor["timeline_frame"])
    bbox = bbox_ref_from_normalized(anchor["normalized_bbox"])
    x0, y0, x1, y1 = bbox
    width = max(4, x1 - x0)
    height = max(4, y1 - y0)

    anchor_image = highpass(cv2.cvtColor(video.read_ref(anchor_frame), cv2.COLOR_BGR2GRAY))
    template = anchor_image[y0:y1, x0:x1].copy()
    require(template.shape[0] >= 4 and template.shape[1] >= 4, "anchor_template_bbox")

    start = max(int(search_window[0]), anchor_frame - TRACK_RADIUS_FRAMES)
    end = min(int(search_window[1]), anchor_frame + TRACK_RADIUS_FRAMES + 1)
    margin_x = max(12, int(round(width * 0.75)))
    margin_y = max(12, int(round(height * 1.00)))
    rx0 = max(0, x0 - margin_x)
    ry0 = max(0, y0 - margin_y)
    rx1 = min(REF_WIDTH, x1 + margin_x)
    ry1 = min(REF_HEIGHT, y1 + margin_y)

    rows = []
    for timeline_frame in range(start, end):
        image = highpass(cv2.cvtColor(video.read_ref(timeline_frame), cv2.COLOR_BGR2GRAY))
        roi = image[ry0:ry1, rx0:rx1]
        best: tuple[float, float, list[int]] | None = None
        for scale in (0.85, 0.925, 1.0, 1.075, 1.15):
            tw = max(4, int(round(width * scale)))
            th = max(4, int(round(height * scale)))
            if tw >= roi.shape[1] or th >= roi.shape[0]:
                continue
            resized = cv2.resize(template, (tw, th), interpolation=cv2.INTER_LINEAR)
            response = cv2.matchTemplate(roi, resized, cv2.TM_CCOEFF_NORMED)
            _, raw_score, _, location = cv2.minMaxLoc(response)
            score = float(raw_score) - 0.02 * abs(math.log(scale))
            candidate_box = [rx0 + location[0], ry0 + location[1], rx0 + location[0] + tw, ry0 + location[1] + th]
            candidate = (score, float(scale), candidate_box)
            if best is None or candidate[0] > best[0]:
                best = candidate
        require(best is not None, f"track_candidate:{timeline_frame}")
        rows.append({
            "timeline_frame": timeline_frame,
            "score": round(best[0], 6),
            "scale": round(best[1], 6),
            "source_bbox_ref": best[2],
        })

    run = strongest_consecutive_run_containing_anchor(rows, anchor_frame, TRACK_STRONG_SCORE)
    return {
        "anchor_frame": anchor_frame,
        "anchor_bbox_ref": bbox,
        "search_window": [start, end],
        "threshold": TRACK_STRONG_SCORE,
        "all_scores": rows,
        "strong_run": run,
        "strong_support": len(run),
        "strong_frames": [int(x["timeline_frame"]) for x in run],
        "visual_window": [int(run[0]["timeline_frame"]), int(run[-1]["timeline_frame"]) + 1] if run else [anchor_frame, anchor_frame + 1],
    }


def compound_membership(vf: Mapping[str, Any], instance_id: str) -> dict[str, Any] | None:
    matches = []
    for owner_id, decomposition in (vf.get("compound_ocr_decompositions") or {}).items():
        if not isinstance(decomposition, Mapping) or decomposition.get("applied") is not True:
            continue
        members = [str(x) for x in decomposition.get("member_ids") or []]
        if instance_id not in members:
            continue
        matches.append({
            "authority_instance_id": str(owner_id),
            "member_ids": members,
            "member_texts": [str(x) for x in decomposition.get("member_texts") or []],
            "source_frames": [int(x) for x in decomposition.get("source_frames") or []],
            "source_ocr_texts": [str(x) for x in decomposition.get("source_ocr_texts") or []],
            "identity_rule": str(decomposition.get("identity_rule") or ""),
            "member_index": members.index(instance_id),
        })
    require(len(matches) <= 1, f"compound_membership_ambiguous:{instance_id}")
    return matches[0] if matches else None


def absence_gate(evidence: Mapping[str, Any]) -> bool:
    """Require independent full-window evidence before claiming not materialized.

    The current accepted recovery artifact only contains sampled OCR candidates,
    so this gate is intentionally unreachable for rows without a future explicit
    full-window semantic/component audit.
    """
    return (
        evidence.get("full_window_semantic_scan") is True
        and evidence.get("neighbor_sequence_closed") is True
        and isinstance(evidence.get("unexplained_text_components"), int)
        and not isinstance(evidence.get("unexplained_text_components"), bool)
        and int(evidence["unexplained_text_components"]) == 0
        and isinstance(evidence.get("semantic_hits"), int)
        and not isinstance(evidence.get("semantic_hits"), bool)
        and int(evidence["semantic_hits"]) == 0
    )


def classify_row(row: Mapping[str, Any], vf: Mapping[str, Any], video: VideoSource) -> dict[str, Any]:
    instance_id = str(row.get("instance_id") or "")
    canonical = str(row.get("canonical_text") or "")
    require(instance_id and canonical, "row_identity")

    base = {
        "instance_id": instance_id,
        "canonical_text": canonical,
        "input_classification": str(row.get("classification") or ""),
        "transcript_timing_authority": False,
        "geometry_only_semantic_promotion": False,
        "negative_ocr_promoted_to_absence": False,
        "resolve_application_authorized": False,
    }

    compound = compound_membership(vf, instance_id)
    if compound is not None:
        base.update({
            "classification": "source_compound_member_represented",
            "basis": "accepted_v2_exact_adjacent_compound_member",
            "compound_membership": compound,
            "source_materialized": True,
            "timing_status": "represented_by_accepted_compound_source_frames",
        })
        return base

    anchors = exact_anchor_candidates(row)
    if anchors:
        anchor = anchors[0]
        search = (row.get("source_pixel_search_prior") or {}).get("source_pixel_search_window")
        require(isinstance(search, list) and len(search) == 2, f"search_window:{instance_id}")
        tracking = track_exact_anchor(video, anchor, search)
        compact = compact_text(canonical)
        min_support = TRACK_SHORT_MIN_SUPPORT if len(compact) <= 3 else TRACK_LONG_MIN_SUPPORT
        base["exact_source_ocr_anchor"] = {
            "timeline_frame": int(anchor["timeline_frame"]),
            "text": str(anchor.get("text") or ""),
            "confidence": round(float(anchor.get("confidence") or 0.0), 6),
            "normalized_bbox": list(anchor.get("normalized_bbox") or []),
        }
        base["source_pixel_tracking"] = tracking
        base["source_materialized"] = True
        if int(tracking["strong_support"]) >= min_support:
            base.update({
                "classification": "source_semantic_track_recovered",
                "basis": "exact_source_ocr_anchor_plus_multiframe_pixel_continuity",
                "timing_status": "source_pixel_window_recovered",
                "visual_window": list(tracking["visual_window"]),
                "support": int(tracking["strong_support"]),
            })
        else:
            base.update({
                "classification": "source_semantic_anchor_only",
                "basis": "exact_source_ocr_anchor_without_sufficient_temporal_continuity",
                "timing_status": "source_identity_confirmed_duration_unresolved",
                "visual_window": [int(anchor["timeline_frame"]), int(anchor["timeline_frame"]) + 1],
                "support": 1,
            })
        return base

    absence_evidence = {
        "full_window_semantic_scan": False,
        "neighbor_sequence_closed": False,
        "unexplained_text_components": None,
        "semantic_hits": None,
        "reason": "accepted_input_contains_sampled_ocr_not_full_window_component_audit",
    }
    if absence_gate(absence_evidence):
        base.update({
            "classification": "source_not_materialized",
            "basis": "multi_signal_full_window_absence_gate",
            "source_materialized": False,
            "timing_status": "not_applicable",
            "absence_evidence": absence_evidence,
        })
        return base

    base.update({
        "classification": "source_still_unresolved",
        "basis": "no_positive_source_identity_and_absence_gate_not_satisfied",
        "source_materialized": None,
        "timing_status": "unresolved",
        "absence_evidence": absence_evidence,
        "retained_probe_evidence": {
            "source_pixel_search_prior": dict(row.get("source_pixel_search_prior") or {}),
            "high_confidence_ocr_candidates": list(row.get("high_confidence_ocr_candidates") or []),
            "neighbor_context": dict(row.get("neighbor_context") or {}),
        },
    })
    return base


def build(repo_root: Path, output_path: Path) -> dict[str, Any]:
    recovery = load_json(repo_root / RECOVERY)
    validation = load_json(repo_root / RECOVERY_VALIDATION)
    vf = load_json(repo_root / VF)
    source = verify_inputs(repo_root, recovery, validation, vf)

    prior_rows = [dict(x) for x in recovery.get("classifications") or [] if isinstance(x, Mapping)]
    remaining = [x for x in prior_rows if x.get("classification") == "source_unresolved_after_recovery"]
    require(len(remaining) == EXPECTED_REMAINING, "remaining_count")

    video = VideoSource(source)
    classifications = []
    try:
        for index, row in enumerate(remaining, start=1):
            result = classify_row(row, vf, video)
            classifications.append(result)
            print(f"[unresolved-source-classification] {index}/{EXPECTED_REMAINING} {result['instance_id']} -> {result['classification']}", flush=True)
    finally:
        video.close()

    counts: dict[str, int] = {}
    for row in classifications:
        key = str(row["classification"])
        counts[key] = counts.get(key, 0) + 1
    require(sum(counts.values()) == EXPECTED_REMAINING, "classification_total")

    not_materialized = counts.get("source_not_materialized", 0)
    require(not_materialized == 0, "unexpected_absence_claim")
    positively_classified = (
        counts.get("source_semantic_track_recovered", 0)
        + counts.get("source_semantic_anchor_only", 0)
        + counts.get("source_compound_member_represented", 0)
    )
    require(positively_classified > 0, "no_positive_classification_progress")

    result = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "ok": True,
        "policy": {
            "primary_authority": "accepted_unresolved_recovery_plus_accepted_visual_fidelity_v2_plus_source_pixels",
            "transcript_timing_authority": False,
            "geometry_only_semantic_promotion": False,
            "negative_ocr_promoted_to_absence": False,
            "single_frame_exact_ocr_may_confirm_identity_but_not_duration": True,
            "semantic_timing_recovery_requires_pixel_continuity": True,
            "source_not_materialized_requires_full_window_multi_signal_absence_gate": True,
            "sampled_negative_ocr_can_prove_absence": False,
            "per_cue_hardcoded_overrides": False,
            "screenshot_specific_overrides": False,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
        "inputs": {
            str(RECOVERY): {"path": str(RECOVERY), "sha256": sha256(repo_root / RECOVERY)},
            str(RECOVERY_VALIDATION): {"path": str(RECOVERY_VALIDATION), "sha256": sha256(repo_root / RECOVERY_VALIDATION)},
            str(VF): {"path": str(VF), "sha256": sha256(repo_root / VF)},
            "source_video": {"path": str(source.relative_to(repo_root)), "sha256": sha256(source)},
        },
        "configuration": {
            "exact_long_min_confidence": EXACT_LONG_MIN_CONFIDENCE,
            "exact_short_min_confidence": EXACT_SHORT_MIN_CONFIDENCE,
            "track_strong_score": TRACK_STRONG_SCORE,
            "track_long_min_support": TRACK_LONG_MIN_SUPPORT,
            "track_short_min_support": TRACK_SHORT_MIN_SUPPORT,
            "track_radius_frames": TRACK_RADIUS_FRAMES,
        },
        "prior_visual_companion_recoveries": [
            dict(row) for row in prior_rows if row.get("classification") == "source_visual_companion_recovered"
        ],
        "classifications": classifications,
        "summary": {
            "evaluated_remaining": len(classifications),
            "source_semantic_track_recovered": counts.get("source_semantic_track_recovered", 0),
            "source_semantic_anchor_only": counts.get("source_semantic_anchor_only", 0),
            "source_compound_member_represented": counts.get("source_compound_member_represented", 0),
            "source_not_materialized": not_materialized,
            "source_still_unresolved": counts.get("source_still_unresolved", 0),
            "source_absent_claims": not_materialized,
            "prior_visual_companion_recovered": EXPECTED_PRIOR_COMPANION_RECOVERED,
            "structural_total": EXPECTED_STRUCTURAL,
            "physical_textplus_before_final_merge": EXPECTED_PHYSICAL,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
        "next_boundary": "MERGE_POSITIVE_RECOVERIES_INTO_VISUAL_FIDELITY_AUTHORITY_AND_CLASSIFY_ONLY_RESIDUAL_AMBIGUITIES_BEFORE_RESOLVE",
        "semantic_sha256": "",
    }
    result["semantic_sha256"] = canonical_sha256({k: v for k, v in result.items() if k != "semantic_sha256"})
    write_json(output_path, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.resolve()
    output = (args.output or (root / DEFAULT_OUTPUT)).resolve()
    result = build(root, output)
    print(json.dumps(result["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
