#!/usr/bin/env python3
"""Final offline visual audit for the nine residual Step 3E caption ambiguities.

This stage is intentionally conservative. It performs an exhaustive OCR scan over
all source frames in each accepted source-pixel search window, then combines only
positive semantic evidence with source-pixel continuity. Negative OCR is retained
as audit evidence but never becomes a source-absence claim.

It also quarantines unsafe *existing* short-token repair authorities when their
semantic identity came from a sparse, low-confidence strict re-anchor. This is a
generic safety gate for logo/glyph false positives; it does not name any cue,
word, screenshot, or video-specific branch.

Offline only. Resolve is never invoked or modified.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import cv2

TASK_ID = "DZSQH7AUHJT_STEP_3E_FINAL_UNRESOLVED9_VISUAL_AUDIT_V1"
CLASSIFICATION = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_SOURCE_CLASSIFICATION_V1/unresolved_source_classification_v1.json")
CLASSIFICATION_VALIDATION = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_SOURCE_CLASSIFICATION_V1/unresolved_source_classification_validation.json")
RECOVERY = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_VISUAL_LAYER_RECOVERY_V1/unresolved_visual_layer_recovery_v1.json")
RECOVERY_VALIDATION = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_VISUAL_LAYER_RECOVERY_V1/unresolved_visual_layer_recovery_validation.json")
VF = Path("artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_AUTHORITY_V2/visual_fidelity_authority_v2.json")
VF_VALIDATION = Path("artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_AUTHORITY_V2/visual_fidelity_authority_validation.json")
UNIVERSAL = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNIVERSAL_VISUAL_REPAIR_AUTHORITY_V1/universal_visual_repair_authority_v1.json")
OCR_MODULE = Path("scripts/davinci/redetect_caption_word_instances_step_3B_6.py")
PRIOR_CLASSIFIER_MODULE = Path("scripts/analysis/build_step_3E_unresolved_source_classification_v1.py")
DEFAULT_OUTPUT = Path("artifacts/DZSQH7AUHJT_STEP_3E_FINAL_UNRESOLVED9_VISUAL_AUDIT_V1/final_unresolved9_visual_audit_v1.json")

EXPECTED_CLASSIFICATION_SHA256 = "b0d390a54e9a73c05059b2725a5ff28aeab1d7ff233d14376507cb82bba77a87"
EXPECTED_CLASSIFICATION_VALIDATION_SHA256 = "7e4bca4b115e5e82c0f0ae25e274843f0fa33a23b559865395ed40f78042ca14"
EXPECTED_RECOVERY_SHA256 = "bb4fab45389dbb10d58970955c6194e3f4d8e7351d79f397074bfb15b2fb8e5d"
EXPECTED_RECOVERY_VALIDATION_SHA256 = "7339bf038feafce8eaefdf3702e1457e67a7fcbc034a34eddf7183b2f7a6b1c7"
EXPECTED_VF_SHA256 = "6f7cdf265dcb18611e7f6326d7d12de7a3dade7b2a7b6d33e1d406d5645ca6f5"
EXPECTED_VF_VALIDATION_SHA256 = "4ec072bce20b2881403ec9468a3d1e7cacb4f26a2f1b1cc0483b0ce7670e7f1a"
EXPECTED_UNIVERSAL_SHA256 = "5fda48532c96ad6452a3c194671dde82e67839b05f70ae45d38615255545b670"
EXPECTED_OCR_MODULE_SHA256 = "92d58347fac594b3452dcb23ab430b6831b36a54f3b52a86a123c2a91dafbc9b"
EXPECTED_VF_BUILDER_SHA256 = "c1fe8a19001fecd8a5d2c48018c553378b5df5c593b5a0d30874dcb584be9c99"
EXPECTED_PRIOR_CLASSIFIER_SHA256 = "aae1f2081e258d8d1d3824f09ecd5658061b204163102053ee9f2059b16f0a76"
EXPECTED_SOURCE_SHA256 = "fd60f596fb09031d8fa41071691cbdc1884edb32fd79f436f6be1df1ca186635"

EXPECTED_RESIDUAL = 9
EXPECTED_STRUCTURAL = 117
EXPECTED_PHYSICAL = 114
TIMELINE_FPS = 24.0
OCR_MAX_SIDE = 1440
OCR_MIN_CONFIDENCE = 0.22
SEMANTIC_MIN_CONFIDENCE = 0.85
SEMANTIC_MIN_SUPPORT = 2
SHORT_ANCHOR_MAX_LENGTH = 3
SHORT_ANCHOR_QUARANTINE_CONFIDENCE = 0.85


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


def load_module(path: Path, name: str):
    require(path.is_file(), f"module:{path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"module_spec:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def source_video_from_vf(repo_root: Path, vf: Mapping[str, Any]) -> Path:
    for row in (vf.get("inputs") or {}).values():
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


def verify_inputs(repo_root: Path, classification: Mapping[str, Any], classification_validation: Mapping[str, Any], recovery: Mapping[str, Any], recovery_validation: Mapping[str, Any], vf: Mapping[str, Any], vf_validation: Mapping[str, Any], universal: Mapping[str, Any]) -> Path:
    expected = {
        CLASSIFICATION: EXPECTED_CLASSIFICATION_SHA256,
        CLASSIFICATION_VALIDATION: EXPECTED_CLASSIFICATION_VALIDATION_SHA256,
        RECOVERY: EXPECTED_RECOVERY_SHA256,
        RECOVERY_VALIDATION: EXPECTED_RECOVERY_VALIDATION_SHA256,
        VF: EXPECTED_VF_SHA256,
        VF_VALIDATION: EXPECTED_VF_VALIDATION_SHA256,
        UNIVERSAL: EXPECTED_UNIVERSAL_SHA256,
        OCR_MODULE: EXPECTED_OCR_MODULE_SHA256,
        Path("scripts/analysis/build_step_3E_visual_fidelity_authority_v2.py"): EXPECTED_VF_BUILDER_SHA256,
        PRIOR_CLASSIFIER_MODULE: EXPECTED_PRIOR_CLASSIFIER_SHA256,
    }
    for rel, digest in expected.items():
        require(sha256(repo_root / rel) == digest, f"input_sha256:{rel}")
    require(classification.get("ok") is True and classification_validation.get("ok") is True, "classification_input_ok")
    require(recovery.get("ok") is True and recovery_validation.get("ok") is True, "recovery_input_ok")
    require(vf.get("ok") is True and vf_validation.get("ok") is True, "vf_input_ok")
    require(universal.get("ok") is True, "universal_input_ok")
    summary = classification.get("summary") or {}
    require(type(summary.get("source_still_unresolved")) is int and summary["source_still_unresolved"] == EXPECTED_RESIDUAL, "residual_count")
    require((classification.get("policy") or {}).get("negative_ocr_promoted_to_absence") is False, "prior_negative_absence")
    require((classification.get("policy") or {}).get("geometry_only_semantic_promotion") is False, "prior_geometry_promotion")
    source = source_video_from_vf(repo_root, vf)
    require(sha256(source) == EXPECTED_SOURCE_SHA256, "source_video_sha256")
    return source


def structural_order(universal: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [dict(x) for x in universal.get("instances") or [] if isinstance(x, Mapping)]
    require(len(rows) == EXPECTED_STRUCTURAL, "structural_rows")
    return rows


def adjacent_compounds(rows: Sequence[Mapping[str, Any]], instance_id: str) -> list[dict[str, Any]]:
    index = next((i for i, row in enumerate(rows) if str(row.get("instance_id")) == instance_id), None)
    require(index is not None, f"structural_instance:{instance_id}")
    spans = []
    for length in (2, 3):
        for start in range(max(0, index - length + 1), min(index + 1, len(rows) - length + 1)):
            members = rows[start:start + length]
            ids = [str(x.get("instance_id") or "") for x in members]
            if instance_id not in ids:
                continue
            texts = [str(x.get("canonical_text") or "") for x in members]
            compact = "".join(compact_text(x) for x in texts)
            if compact:
                spans.append({"member_ids": ids, "member_texts": texts, "compact_text": compact, "member_index": ids.index(instance_id)})
    return spans


def scan_window(repo_root: Path, ocr: Any, engine: Any, cap: cv2.VideoCapture, temp_dir: Path, source_fps: float, source_count: int, source_width: int, source_height: int, window: Sequence[int], cache: dict[int, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    start, end = int(window[0]), int(window[1])
    require(0 <= start < end, f"scan_window:{window}")
    rows = []
    for timeline_frame in range(start, end):
        if timeline_frame not in cache:
            source_frame = max(0, min(source_count - 1, int(round(timeline_frame * source_fps / TIMELINE_FPS))))
            cap.set(cv2.CAP_PROP_POS_FRAMES, source_frame)
            ok, frame = cap.read()
            require(ok and frame is not None, f"scan_frame:{timeline_frame}:{source_frame}")
            ocr_frame, scale_x, scale_y = ocr.resize_for_ocr(frame, OCR_MAX_SIDE)
            parsed = ocr.parse_paddle_result(ocr.run_ocr(engine, ocr_frame, temp_dir, f"u9_{timeline_frame}"))
            candidates = ocr.build_candidates(parsed, scale_x, scale_y, source_width, source_height, OCR_MIN_CONFIDENCE)
            serialized = []
            for cand in candidates:
                bbox = [float(v) for v in getattr(cand, "bbox", [0, 0, 1, 1])]
                serialized.append({
                    "timeline_frame": timeline_frame,
                    "source_frame": source_frame,
                    "text": str(getattr(cand, "text", "")),
                    "source_text": str(getattr(cand, "source_text", "")),
                    "confidence": round(float(getattr(cand, "confidence", 0.0)), 6),
                    "source_kind": str(getattr(cand, "source_kind", "")),
                    "normalized_bbox": [
                        round(bbox[0] / source_width, 8), round(bbox[1] / source_height, 8),
                        round(bbox[2] / source_width, 8), round(bbox[3] / source_height, 8),
                    ],
                })
            cache[timeline_frame] = serialized
        rows.extend(dict(x) for x in cache[timeline_frame])
    return rows


def semantic_observations(canonical: str, candidates: Sequence[Mapping[str, Any]], vf_builder: Any) -> list[dict[str, Any]]:
    out = []
    for row in candidates:
        confidence = float(row.get("confidence") or 0.0)
        if confidence < SEMANTIC_MIN_CONFIDENCE:
            continue
        if not vf_builder.strict_ocr_semantic_match(canonical, row.get("text"), confidence):
            continue
        item = dict(row)
        item["semantic_rule"] = "accepted_visual_fidelity_v2_strict_ocr_semantic_match"
        out.append(item)
    return out


def compound_observations(compounds: Sequence[Mapping[str, Any]], candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for candidate in candidates:
        confidence = float(candidate.get("confidence") or 0.0)
        if confidence < SEMANTIC_MIN_CONFIDENCE:
            continue
        text = compact_text(candidate.get("text"))
        for span in compounds:
            if text != str(span.get("compact_text") or ""):
                continue
            item = dict(candidate)
            item.update({
                "member_ids": list(span.get("member_ids") or []),
                "member_texts": list(span.get("member_texts") or []),
                "member_index": int(span.get("member_index") or 0),
                "semantic_rule": "exact_adjacent_compact_concatenation",
            })
            result.append(item)
    return result


def distinct_frame_count(rows: Sequence[Mapping[str, Any]]) -> int:
    return len({int(x.get("timeline_frame") or -1) for x in rows})


def recover_semantic_with_tracking(prior_classifier: Any, source: Path, row: Mapping[str, Any], semantic: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not semantic:
        return None
    best = max(semantic, key=lambda x: (float(x.get("confidence") or 0.0), -int(x.get("timeline_frame") or 0)))
    search = ((row.get("retained_probe_evidence") or {}).get("source_pixel_search_prior") or {}).get("source_pixel_search_window")
    require(isinstance(search, list) and len(search) == 2, f"search_window:{row.get('instance_id')}")
    video = prior_classifier.VideoSource(source)
    try:
        tracking = prior_classifier.track_exact_anchor(video, best, search)
    finally:
        video.close()
    compact = compact_text(row.get("canonical_text"))
    min_support = prior_classifier.TRACK_SHORT_MIN_SUPPORT if len(compact) <= 3 else prior_classifier.TRACK_LONG_MIN_SUPPORT
    if int(tracking.get("strong_support") or 0) < int(min_support):
        return None
    return {
        "classification": "recovered_semantic",
        "basis": "full_window_strict_semantic_ocr_plus_source_pixel_continuity",
        "source_materialized": True,
        "visual_window": list(tracking.get("visual_window") or []),
        "semantic_observations": [dict(x) for x in semantic],
        "source_pixel_tracking": tracking,
        "resolve_application_authorized": False,
    }


def sparse_short_anchor_quarantines(vf: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    for row in vf.get("repair_instances") or []:
        if not isinstance(row, Mapping):
            continue
        anchor = row.get("source_anchor") or {}
        canonical = compact_text(row.get("canonical_text"))
        if len(canonical) > SHORT_ANCHOR_MAX_LENGTH or not canonical:
            continue
        if anchor.get("method") != "strict_exact_short_token_reanchor":
            continue
        confidence = float(anchor.get("ocr_confidence") or 0.0)
        if confidence >= SHORT_ANCHOR_QUARANTINE_CONFIDENCE:
            continue
        if row.get("tracking_basis") == "source_semantic_ocr_temporal_consensus":
            continue
        result.append({
            "instance_id": str(row.get("instance_id") or ""),
            "canonical_text": str(row.get("canonical_text") or ""),
            "reason": "short_exact_identity_has_only_sparse_low_confidence_ocr_anchor",
            "anchor_confidence": round(confidence, 6),
            "anchor_frame": int(anchor.get("timeline_frame") or -1),
            "visual_window": list(row.get("visual_window") or []),
            "tracking_basis": str(row.get("tracking_basis") or ""),
            "final_rollout_action": "remove_or_do_not_materialize_semantic_textplus_until_multiframe_semantics_exist",
            "cue_specific_rule": False,
        })
    return result


def audit_row(repo_root: Path, row: Mapping[str, Any], source: Path, structural: Sequence[Mapping[str, Any]], ocr: Any, engine: Any, cap: cv2.VideoCapture, temp_dir: Path, meta: Mapping[str, Any], cache: dict[int, list[dict[str, Any]]], vf_builder: Any, prior_classifier: Any) -> dict[str, Any]:
    instance_id = str(row.get("instance_id") or "")
    canonical = str(row.get("canonical_text") or "")
    require(instance_id and canonical, "row_identity")
    prior = row.get("retained_probe_evidence") or {}
    search = (prior.get("source_pixel_search_prior") or {}).get("source_pixel_search_window")
    require(isinstance(search, list) and len(search) == 2, f"audit_window:{instance_id}")
    candidates = scan_window(
        repo_root, ocr, engine, cap, temp_dir,
        float(meta["source_fps"]), int(meta["source_count"]), int(meta["source_width"]), int(meta["source_height"]),
        search, cache,
    )
    semantic = semantic_observations(canonical, candidates, vf_builder)
    compound = compound_observations(adjacent_compounds(structural, instance_id), candidates)
    recovered = recover_semantic_with_tracking(prior_classifier, source, row, semantic)
    base = {
        "instance_id": instance_id,
        "canonical_text": canonical,
        "input_classification": str(row.get("classification") or ""),
        "full_window_ocr_scan": True,
        "audit_window": [int(search[0]), int(search[1])],
        "frames_scanned": int(search[1]) - int(search[0]),
        "ocr_candidate_count": len(candidates),
        "semantic_hit_frames": distinct_frame_count(semantic),
        "compound_hit_frames": distinct_frame_count(compound),
        "transcript_timing_authority": False,
        "geometry_only_semantic_promotion": False,
        "negative_ocr_promoted_to_absence": False,
        "source_absence_claimed": False,
        "resolve_application_authorized": False,
    }
    if recovered is not None:
        base.update(recovered)
        return base
    if distinct_frame_count(compound) >= SEMANTIC_MIN_SUPPORT:
        strongest = max(compound, key=lambda x: float(x.get("confidence") or 0.0))
        base.update({
            "classification": "represented_by_existing_visual_layer",
            "basis": "full_window_exact_adjacent_compound_source_layer",
            "source_materialized": True,
            "compound_observations": compound,
            "represented_member_ids": list(strongest.get("member_ids") or []),
            "timing_status": "represented_by_compound_source_layer",
        })
        return base
    base.update({
        "classification": "unresolved_after_full_visual_audit",
        "basis": "full_window_scan_found_no_safe_multiframe_semantic_or_compound_authority",
        "source_materialized": None,
        "timing_status": "unresolved",
        "semantic_observations": semantic,
        "compound_observations": compound,
        "audit_evidence": {
            "sampled_candidate_rows": candidates[:80],
            "candidate_rows_truncated": len(candidates) > 80,
            "negative_scan_is_not_absence": True,
        },
    })
    return base


def build(repo_root: Path, output_path: Path, ocr_device: str = "gpu:0", ocr_gpu_id: int = 0) -> dict[str, Any]:
    classification = load_json(repo_root / CLASSIFICATION)
    classification_validation = load_json(repo_root / CLASSIFICATION_VALIDATION)
    recovery = load_json(repo_root / RECOVERY)
    recovery_validation = load_json(repo_root / RECOVERY_VALIDATION)
    vf = load_json(repo_root / VF)
    vf_validation = load_json(repo_root / VF_VALIDATION)
    universal = load_json(repo_root / UNIVERSAL)
    source = verify_inputs(repo_root, classification, classification_validation, recovery, recovery_validation, vf, vf_validation, universal)

    residual = [dict(x) for x in classification.get("classifications") or [] if isinstance(x, Mapping) and x.get("classification") == "source_still_unresolved"]
    require(len(residual) == EXPECTED_RESIDUAL, "residual_rows")
    structural = structural_order(universal)

    ocr = load_module(repo_root / OCR_MODULE, "vc_final_unresolved9_ocr")
    vf_builder = load_module(repo_root / Path("scripts/analysis/build_step_3E_visual_fidelity_authority_v2.py"), "vc_final_unresolved9_vf")
    prior_classifier = load_module(repo_root / PRIOR_CLASSIFIER_MODULE, "vc_final_unresolved9_prior")
    engine, engine_info = ocr.create_ocr("en", ocr_device, ocr_gpu_id)

    cap = cv2.VideoCapture(str(source))
    require(cap.isOpened(), f"video_open:{source}")
    meta = {
        "source_fps": float(cap.get(cv2.CAP_PROP_FPS) or 0.0),
        "source_count": int(round(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)),
        "source_width": int(round(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)),
        "source_height": int(round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)),
    }
    require(meta["source_fps"] > 0 and meta["source_count"] > 0 and meta["source_width"] > 0 and meta["source_height"] > 0, "video_meta")

    rows = []
    cache: dict[int, list[dict[str, Any]]] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="vc_final_u9_") as temp_name:
            temp_dir = Path(temp_name)
            for index, row in enumerate(residual, start=1):
                result = audit_row(repo_root, row, source, structural, ocr, engine, cap, temp_dir, meta, cache, vf_builder, prior_classifier)
                rows.append(result)
                print(f"[final-unresolved9-audit] {index}/{EXPECTED_RESIDUAL} {result['instance_id']} -> {result['classification']}", flush=True)
    finally:
        cap.release()

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    require(sum(counts.values()) == EXPECTED_RESIDUAL, "audit_total")

    quarantines = sparse_short_anchor_quarantines(vf)
    require(len(quarantines) >= 1, "no_sparse_short_anchor_quarantine")

    result = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "ok": True,
        "policy": {
            "primary_authority": "accepted_v2_authority_plus_full_window_source_ocr_plus_source_pixel_continuity",
            "all_residual_rows_receive_full_window_ocr_scan": True,
            "negative_ocr_promoted_to_absence": False,
            "source_absence_claims_allowed": False,
            "geometry_only_semantic_promotion": False,
            "transcript_timing_authority": False,
            "semantic_recovery_requires_source_pixel_continuity": True,
            "compound_representation_requires_exact_adjacent_concatenation_multiframe": True,
            "sparse_low_confidence_short_semantic_anchors_are_quarantined": True,
            "per_cue_hardcoded_overrides": False,
            "screenshot_specific_overrides": False,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
            "offline_recovery_stops_after_this_boundary": True,
        },
        "inputs": {
            str(CLASSIFICATION): {"path": str(CLASSIFICATION), "sha256": sha256(repo_root / CLASSIFICATION)},
            str(CLASSIFICATION_VALIDATION): {"path": str(CLASSIFICATION_VALIDATION), "sha256": sha256(repo_root / CLASSIFICATION_VALIDATION)},
            str(RECOVERY): {"path": str(RECOVERY), "sha256": sha256(repo_root / RECOVERY)},
            str(RECOVERY_VALIDATION): {"path": str(RECOVERY_VALIDATION), "sha256": sha256(repo_root / RECOVERY_VALIDATION)},
            str(VF): {"path": str(VF), "sha256": sha256(repo_root / VF)},
            str(VF_VALIDATION): {"path": str(VF_VALIDATION), "sha256": sha256(repo_root / VF_VALIDATION)},
            str(UNIVERSAL): {"path": str(UNIVERSAL), "sha256": sha256(repo_root / UNIVERSAL)},
            str(OCR_MODULE): {"path": str(OCR_MODULE), "sha256": sha256(repo_root / OCR_MODULE)},
            "scripts/analysis/build_step_3E_visual_fidelity_authority_v2.py": {"path": "scripts/analysis/build_step_3E_visual_fidelity_authority_v2.py", "sha256": sha256(repo_root / Path("scripts/analysis/build_step_3E_visual_fidelity_authority_v2.py"))},
            str(PRIOR_CLASSIFIER_MODULE): {"path": str(PRIOR_CLASSIFIER_MODULE), "sha256": sha256(repo_root / PRIOR_CLASSIFIER_MODULE)},
            "source_video": {"path": str(source.relative_to(repo_root)), "sha256": sha256(source)},
        },
        "configuration": {
            "ocr_engine": engine_info.get("engine"),
            "ocr_device": engine_info.get("selected_device"),
            "ocr_max_side": OCR_MAX_SIDE,
            "ocr_min_confidence": OCR_MIN_CONFIDENCE,
            "semantic_min_confidence": SEMANTIC_MIN_CONFIDENCE,
            "semantic_min_support": SEMANTIC_MIN_SUPPORT,
            "short_anchor_quarantine_max_length": SHORT_ANCHOR_MAX_LENGTH,
            "short_anchor_quarantine_confidence": SHORT_ANCHOR_QUARANTINE_CONFIDENCE,
            "timeline_fps": TIMELINE_FPS,
        },
        "audits": rows,
        "repair_authority_quarantine": quarantines,
        "summary": {
            "evaluated_residual": len(rows),
            "recovered_semantic": counts.get("recovered_semantic", 0),
            "recovered_visual_companion": counts.get("recovered_visual_companion", 0),
            "represented_by_existing_visual_layer": counts.get("represented_by_existing_visual_layer", 0),
            "unresolved_after_full_visual_audit": counts.get("unresolved_after_full_visual_audit", 0),
            "source_absent_claims": 0,
            "sparse_short_anchor_quarantines": len(quarantines),
            "prior_visual_companion_recovered": 1,
            "structural_total": EXPECTED_STRUCTURAL,
            "physical_textplus_before_final_rollout": EXPECTED_PHYSICAL,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
        "next_boundary": "BUILD_ISOLATED_VISUAL_FIDELITY_V2_RESOLVE_ROLLOUT_USING_RECOVERIES_RESIDUAL_PRESERVE_AND_QUARANTINE_ACTIONS",
        "semantic_sha256": "",
    }
    result["semantic_sha256"] = canonical_sha256({k: v for k, v in result.items() if k != "semantic_sha256"})
    write_json(output_path, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--ocr-device", default="gpu:0")
    parser.add_argument("--ocr-gpu-id", type=int, default=0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.resolve()
    output = (args.output or (root / DEFAULT_OUTPUT)).resolve()
    result = build(root, output, args.ocr_device, args.ocr_gpu_id)
    print(json.dumps(result["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
