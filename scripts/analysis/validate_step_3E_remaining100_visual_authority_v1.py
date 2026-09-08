#!/usr/bin/env python3
"""Validate the remaining-100 visual authority without invoking Resolve."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

TASK_ID = "DZSQH7AUHJT_STEP_3E_REMAINING100_VISUAL_AUTHORITY_V1"
EXPECTED_INSTANCE_COUNT = 100
EXPECTED_V4_TOKEN_COUNT = 17
EXPECTED_V4_SOURCE_CUE_COUNT = 15
FULL_PLAN = Path(
    ".agent/reports/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_FULL_ROLLOUT_BASELINE_V1/"
    "20260810T080927254297Z_befb7b9f1474440fb817520c47ba8cd3/full_rollout_plan.json"
)
V4_AUTHORITY = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_authority_v4.json")
DEFAULT_AUTHORITY = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_REMAINING100_VISUAL_AUTHORITY_V1/"
    "remaining100_visual_authority_v1.json"
)
DEFAULT_OUTPUT = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_REMAINING100_VISUAL_AUTHORITY_V1/"
    "remaining100_visual_authority_validation.json"
)


class ValidationError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValidationError(code)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def cue_key(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("sub_") and text[4:].isdigit():
        return f"sub_{int(text[4:]):03d}"
    return text


def validate_frame_path(instance: Mapping[str, Any]) -> int:
    path = instance.get("frame_path")
    require(isinstance(path, list) and path, f"frame_path:{instance.get('instance_id')}")
    window = instance.get("visual_window")
    require(isinstance(window, list) and len(window) == 2, f"visual_window:{instance.get('instance_id')}")
    start, end = int(window[0]), int(window[1])
    require(end > start, f"visual_window_order:{instance.get('instance_id')}")
    require(len(path) == end - start, f"frame_path_dense:{instance.get('instance_id')}")
    previous = None
    for row in path:
        require(isinstance(row, Mapping), "frame_row")
        frame = row.get("timeline_frame")
        require(isinstance(frame, int), "frame_number")
        require(start <= frame < end, "frame_in_window")
        require(previous is None or frame == previous + 1, "frame_dense_order")
        previous = frame

        top = row.get("position_top_origin")
        fusion = row.get("position_fusion")
        require(isinstance(top, list) and len(top) == 2, "position_top_origin")
        require(isinstance(fusion, list) and len(fusion) == 2, "position_fusion")
        require(all(isinstance(v, (int, float)) and 0.0 <= float(v) <= 1.0 for v in top), "position_top_bounds")
        require(all(isinstance(v, (int, float)) and 0.0 <= float(v) <= 1.0 for v in fusion), "position_fusion_bounds")
        require(abs(float(top[0]) - float(fusion[0])) <= 1e-5, "position_x_conversion")
        require(abs((1.0 - float(top[1])) - float(fusion[1])) <= 2e-5, "position_y_conversion")

        opacity = row.get("opacity_factor")
        size_scale = row.get("size_scale")
        size = row.get("application_size_candidate")
        require(isinstance(opacity, (int, float)) and 0.0 <= float(opacity) <= 1.0, "opacity_bounds")
        require(isinstance(size_scale, (int, float)) and 0.4 <= float(size_scale) <= 1.6, "size_scale_bounds")
        require(isinstance(size, (int, float)) and float(size) > 0.0, "size_candidate")
    return len(path)


def validate(repo_root: Path, authority_path: Path) -> dict[str, Any]:
    full_plan = load_json(repo_root / FULL_PLAN)
    v4 = load_json(repo_root / V4_AUTHORITY)
    authority = load_json(authority_path)

    require(authority.get("task_id") == TASK_ID, "task_id")
    require(authority.get("ok") is True, "authority_ok")
    policy = authority.get("authority_policy") or {}
    require(policy.get("transcript_timing_authority") is False, "transcript_timing_authority")
    require(policy.get("resolve_modified") is False, "resolve_modified")
    require(policy.get("protected_v4_tokens_modified") is False, "protected_v4_tokens_modified")
    require(policy.get("remaining_caption_rollout_authorized") is False, "rollout_authorized")
    require(policy.get("explicit_frame_paths_required") is True, "explicit_paths_policy")

    preserved = ((full_plan.get("replacements") or {}).get("preserved_rows") or [])
    require(len(preserved) == EXPECTED_INSTANCE_COUNT, "baseline_preserved_count")
    expected_ids = [str(row.get("instance_id") or "") for row in preserved]
    require(len(expected_ids) == len(set(expected_ids)) == EXPECTED_INSTANCE_COUNT, "baseline_instance_identity")

    v4_tokens = [
        token
        for group in v4.get("groups") or []
        for token in group.get("tokens") or []
        if isinstance(token, Mapping)
    ]
    protected_cues = {
        cue_key(token.get("source_cue_id"))
        for token in v4_tokens
        if cue_key(token.get("source_cue_id"))
    }
    require(len(v4_tokens) == EXPECTED_V4_TOKEN_COUNT, "v4_token_count")
    require(len(protected_cues) == EXPECTED_V4_SOURCE_CUE_COUNT, "v4_source_cue_count")

    instances = authority.get("instances")
    require(isinstance(instances, list) and len(instances) == EXPECTED_INSTANCE_COUNT, "authority_instance_count")
    actual_ids = [str(row.get("instance_id") or "") for row in instances]
    require(actual_ids == expected_ids, "preserved_instance_order")
    require(len(actual_ids) == len(set(actual_ids)), "authority_instance_identity")

    visual_primary = 0
    pixel_redetected = 0
    low_confidence = 0
    total_rows = 0
    for row in instances:
        cue_ids = [cue_key(value) for value in row.get("source_cue_ids") or [] if cue_key(value)]
        require(cue_ids, f"source_cues:{row.get('instance_id')}")
        require(not (set(cue_ids) & protected_cues), f"protected_overlap:{row.get('instance_id')}")
        require(row.get("transcript_timing_authority") is False, f"transcript_timing:{row.get('instance_id')}")

        timing = str(row.get("visual_timing_authority") or "")
        if timing == "accepted_source_visual_track_plus_pixel_readback":
            visual_primary += 1
        elif timing == "source_pixel_redetection":
            pixel_redetected += 1
            scan = row.get("source_pixel_scan") or {}
            require(int(scan.get("detected_frame_count") or 0) >= 1, f"pixel_detected:{row.get('instance_id')}")
            require(float(scan.get("peak_score") or 0.0) > 0.0, f"pixel_peak:{row.get('instance_id')}")
        else:
            raise ValidationError(f"timing_authority:{row.get('instance_id')}:{timing}")

        scan = row.get("source_pixel_scan") or {}
        if scan.get("confidence") == "low":
            low_confidence += 1
        count = validate_frame_path(row)
        require(int(row.get("explicit_frame_row_count") or 0) == count, f"row_count:{row.get('instance_id')}")
        total_rows += count

    summary = authority.get("summary") or {}
    require(int(summary.get("remaining_instance_count") or 0) == EXPECTED_INSTANCE_COUNT, "summary_instance_count")
    require(int(summary.get("accepted_visual_primary_instance_count") or -1) == visual_primary, "summary_visual_primary")
    require(int(summary.get("source_pixel_redetected_instance_count") or -1) == pixel_redetected, "summary_pixel_redetected")
    require(visual_primary + pixel_redetected == EXPECTED_INSTANCE_COUNT, "authority_partition")
    require(pixel_redetected > 0, "pixel_redetection_required")
    require(int(summary.get("explicit_frame_row_count") or 0) == total_rows, "summary_frame_rows")
    require(int(summary.get("protected_v4_token_count") or 0) == EXPECTED_V4_TOKEN_COUNT, "summary_v4_tokens")
    require(int(summary.get("protected_v4_source_cue_count") or 0) == EXPECTED_V4_SOURCE_CUE_COUNT, "summary_v4_cues")
    require(summary.get("resolve_modified") is False, "summary_resolve_modified")
    require(summary.get("remaining_caption_rollout_authorized") is False, "summary_rollout_authorized")

    expected_semantic = canonical_sha256({k: v for k, v in authority.items() if k != "semantic_sha256"})
    require(authority.get("semantic_sha256") == expected_semantic, "semantic_sha256")

    result = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "ok": True,
        "authority_path": str(authority_path.relative_to(repo_root)),
        "checks": {
            "exact_preserved_instance_set": True,
            "protected_v4_excluded": True,
            "transcript_timing_authority_false": True,
            "explicit_dense_frame_paths": True,
            "pixel_redetection_has_source_evidence": True,
            "resolve_modified_false": True,
            "remaining_rollout_unauthorized": True,
            "semantic_hash_valid": True,
        },
        "counts": {
            "remaining_instances": EXPECTED_INSTANCE_COUNT,
            "visual_primary_instances": visual_primary,
            "pixel_redetected_instances": pixel_redetected,
            "low_confidence_instances": low_confidence,
            "explicit_frame_rows": total_rows,
            "protected_v4_tokens": EXPECTED_V4_TOKEN_COUNT,
        },
        "next_boundary": "STEP_3E_REMAINING100_FULL_ROLLOUT_V1",
    }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--authority", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    authority = args.authority.resolve() if args.authority else (root / DEFAULT_AUTHORITY)
    output = args.output.resolve() if args.output else (root / DEFAULT_OUTPUT)
    try:
        result = validate(root, authority)
        write_json(output, result)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {TASK_ID}: {type(exc).__name__}: {exc}")
        return 1
    print(
        f"PASS {TASK_ID}: instances={result['counts']['remaining_instances']} "
        f"rows={result['counts']['explicit_frame_rows']} "
        f"pixel_redetected={result['counts']['pixel_redetected_instances']}"
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
