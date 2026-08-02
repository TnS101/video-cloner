#!/usr/bin/env python3
"""Validate Major Step 3B.6B dense word-instance re-detection output."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

VERSION = "validate_caption_word_instance_redetection_step_3B_6B_v1_0"
EXPECTED_V3_COUNT = 116
EXPECTED_TARGET_COUNT = 75
EXPECTED_SCENE_COUNT = 15
ACCEPTED_WORKSPACE_VERSIONS = {
    "redetect_caption_word_instances_step_3B_6B_v1_0_dense_paddle_track",
}


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


def canonical_hash(value: Dict[str, Any]) -> str:
    clean = dict(value)
    clean.pop("tracks_hash", None)
    clean.pop("validation_hash", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def bbox_valid(box: Any) -> bool:
    if not isinstance(box, (list, tuple)) or len(box) != 4 or not all(finite(v) for v in box):
        return False
    x1, y1, x2, y2 = [float(v) for v in box]
    return 0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0


def point_valid(point: Any) -> bool:
    return isinstance(point, (list, tuple)) and len(point) == 2 and all(finite(v) for v in point) and all(0.0 <= float(v) <= 1.0 for v in point)


def exact_bbox_key(box: Sequence[float]) -> Tuple[int, int, int, int]:
    return tuple(int(round(float(value) * 1_000_000)) for value in box)  # type: ignore[return-value]


def validate(args: argparse.Namespace) -> Dict[str, Any]:
    tracks_path = Path(args.tracks).resolve()
    plan_path = Path(args.redetection_plan).resolve()
    audit_path = Path(args.audit).resolve()
    output_path = Path(args.output).resolve()
    tracks = load_json(tracks_path)
    plan = load_json(plan_path)
    audit = load_json(audit_path)

    failures: List[str] = []
    warnings: List[str] = []
    checks: Dict[str, bool] = {}
    summary = tracks.get("summary") or {}
    scenes = [scene for scene in (tracks.get("scenes") or []) if isinstance(scene, dict)]
    rows = [row for row in (tracks.get("tracks") or []) if isinstance(row, dict)]
    plan_targets = [row for row in (plan.get("cue_targets") or []) if isinstance(row, dict)]

    checks["tracks_ok"] = bool(tracks.get("ok"))
    checks["workspace_version"] = tracks.get("version") in ACCEPTED_WORKSPACE_VERSIONS
    checks["schema"] = tracks.get("schema") == "video_cloner_caption_word_instance_tracks"
    checks["tracks_hash"] = tracks.get("tracks_hash") == canonical_hash(tracks)
    checks["plan_ok"] = bool(plan.get("ok"))
    checks["audit_ok"] = bool(audit.get("ok"))
    checks["plan_hash_match"] = tracks.get("redetection_plan_hash") == plan.get("plan_hash")
    checks["audit_hash_match"] = tracks.get("source_audit_hash") == audit.get("audit_hash")
    checks["source_is_original"] = not bool((tracks.get("source_video_info") or {}).get("is_proxy"))
    checks["timeline_read_only"] = tracks.get("timeline_modified") is False and summary.get("timeline_modified") is False
    checks["scene_count"] = len(scenes) == EXPECTED_SCENE_COUNT and int(summary.get("scene_count") or 0) == EXPECTED_SCENE_COUNT
    checks["target_count"] = len(rows) == EXPECTED_TARGET_COUNT and int(summary.get("target_cue_count") or 0) == EXPECTED_TARGET_COUNT
    checks["unique_cues"] = len({str(row.get("cue_id")) for row in rows}) == EXPECTED_TARGET_COUNT
    checks["plan_target_partition"] = {str(row.get("cue_id")) for row in rows} == {str(row.get("cue_id")) for row in plan_targets}
    checks["v3_count"] = int(summary.get("v3_item_count") or 0) == EXPECTED_V3_COUNT
    checks["hard_outline_forbidden"] = bool((tracks.get("effect_policy") or {}).get("solid_outline_100pct_no_blur_forbidden"))
    checks["no_report_failures"] = not bool(tracks.get("failures"))

    malformed_observations = 0
    false_exact_rows = 0
    duplicate_exact_boxes = 0
    accepted_count = 0
    unresolved_count = 0
    accepted_without_ocr = 0
    accepted_low_coverage = 0
    unresolved_without_reason = 0
    frames_by_scene: Dict[str, Dict[int, Dict[Tuple[int, int, int, int], str]]] = defaultdict(lambda: defaultdict(dict))

    for row in rows:
        accepted = bool(row.get("accepted_source_instance"))
        exactness = str(row.get("source_exactness") or "")
        confidence = row.get("confidence") or {}
        observations = [item for item in (row.get("frame_observations") or []) if isinstance(item, dict)]
        frames = [int(item.get("timeline_frame") or -1) for item in observations]
        if frames != sorted(set(frames)):
            malformed_observations += 1
        for item in observations:
            if not bbox_valid(item.get("normalized_bbox")) or not point_valid(item.get("position")):
                malformed_observations += 1
                continue
            if not finite(item.get("scale_proxy")) or not finite(item.get("opacity_proxy")):
                malformed_observations += 1
            if not 0.0 <= float(item.get("opacity_proxy")) <= 1.0:
                malformed_observations += 1
            scene_id = str(row.get("scene_id") or "")
            frame = int(item.get("timeline_frame") or -1)
            key = exact_bbox_key(item["normalized_bbox"])
            prior = frames_by_scene[scene_id][frame].get(key)
            if prior and prior != row.get("cue_id"):
                duplicate_exact_boxes += 1
            frames_by_scene[scene_id][frame][key] = str(row.get("cue_id"))
        if accepted:
            accepted_count += 1
            if exactness != "source_redetected_dense_word_instance":
                false_exact_rows += 1
            if int(confidence.get("direct_ocr_frame_count") or 0) < 1:
                accepted_without_ocr += 1
            if float(confidence.get("cue_window_coverage") or 0.0) < 0.45:
                accepted_low_coverage += 1
        else:
            unresolved_count += 1
            if exactness != "unresolved_not_source_exact":
                false_exact_rows += 1
            if not row.get("fallback_reasons"):
                unresolved_without_reason += 1

    checks["all_items_accounted"] = accepted_count + unresolved_count == EXPECTED_TARGET_COUNT
    checks["summary_partition"] = accepted_count == int(summary.get("accepted_source_instance_count", -1)) and unresolved_count == int(summary.get("unresolved_source_instance_count", -1))
    checks["observation_contract"] = malformed_observations == 0
    checks["no_false_exact_claims"] = false_exact_rows == 0
    checks["accepted_has_ocr_seed"] = accepted_without_ocr == 0
    checks["accepted_has_minimum_coverage"] = accepted_low_coverage == 0
    checks["unresolved_has_reason"] = unresolved_without_reason == 0
    checks["no_shared_exact_word_boxes"] = duplicate_exact_boxes == 0
    checks["dense_observations_exist"] = int(summary.get("dense_frame_observation_count") or 0) > 0
    checks["debug_scene_outputs"] = all(scene.get("debug_contact_sheet") for scene in scenes)
    checks["scene_probe_readiness_reported"] = "scene_probe_ready_count" in summary and "preferred_probe_scene_id" in summary

    # Detection is allowed to be conservative. Unresolved cues do not fail this step;
    # silently claiming them as exact would fail it.
    if unresolved_count:
        warnings.append(f"{unresolved_count} target cue(s) remain unresolved. They must stay excluded from source-exact rollout.")
    if int(summary.get("scene_probe_ready_count") or 0) == 0:
        warnings.append("No scene reached the configured 70% acceptance threshold. Tune/re-run Step 3B.6B before Step 3B.6C.")
    if summary.get("preferred_probe_scene_id") != "caption_scene_008":
        warnings.append("The known back/hand scene is not yet the preferred probe scene; use the highest-confidence emitted scene instead.")

    for name, passed in checks.items():
        if not passed:
            failures.append(name)

    result: Dict[str, Any] = {
        "ok": not failures,
        "step": "Major Step 3B.6B",
        "validator_version": VERSION,
        "tracks": str(tracks_path),
        "redetection_plan": str(plan_path),
        "audit": str(audit_path),
        "summary": {
            "v3_item_count": int(summary.get("v3_item_count") or 0),
            "scene_count": len(scenes),
            "target_cue_count": len(rows),
            "accepted_source_instance_count": accepted_count,
            "unresolved_source_instance_count": unresolved_count,
            "dense_frame_observation_count": int(summary.get("dense_frame_observation_count") or 0),
            "scene_probe_ready_count": int(summary.get("scene_probe_ready_count") or 0),
            "preferred_probe_scene_id": summary.get("preferred_probe_scene_id"),
            "malformed_observation_count": malformed_observations,
            "false_exact_row_count": false_exact_rows,
            "duplicate_exact_bbox_assignment_count": duplicate_exact_boxes,
        },
        "checks": checks,
        "warnings": warnings,
        "failures": failures,
        "output": str(output_path),
    }
    result["validation_hash"] = canonical_hash(result)
    write_json(output_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracks", required=True)
    parser.add_argument("--redetection-plan", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main() -> int:
    result = validate(build_parser().parse_args())
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
