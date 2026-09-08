#!/usr/bin/env python3
"""Validate Step 3E semantic source coverage without Resolve."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import median
from typing import Any, Mapping

TASK_ID = "DZSQH7AUHJT_STEP_3E_SEMANTIC_SOURCE_COVERAGE_V1"
EXPECTED_EXCLUDED = 53
CURRENT_AUTHORITY = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_UNIVERSAL_VISUAL_REPAIR_AUTHORITY_V1/"
    "universal_visual_repair_authority_v1.json"
)
DEFAULT_COVERAGE = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_SEMANTIC_SOURCE_COVERAGE_V1/"
    "semantic_source_coverage_v1.json"
)
DEFAULT_OUTPUT = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_SEMANTIC_SOURCE_COVERAGE_V1/"
    "semantic_source_coverage_validation.json"
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
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_confirmed(row: Mapping[str, Any], config: Mapping[str, Any]) -> None:
    observations = row.get("semantic_observations")
    require(isinstance(observations, list) and observations, f"confirmed_observations:{row.get('instance_id')}")
    frames = [int(item.get("timeline_frame")) for item in observations if isinstance(item, Mapping)]
    require(len(frames) == len(set(frames)), f"confirmed_duplicate_frames:{row.get('instance_id')}")
    similarities = [float(item.get("text_similarity") or 0.0) for item in observations]
    confidences = [float(item.get("ocr_confidence") or 0.0) for item in observations]
    if len(observations) == 1:
        reasons = list((row.get("probe_evidence") or {}).get("reasons") or [])
        require("single_frame_source_caption_high_confidence" in reasons, f"confirmed_single_frame_contract:{row.get('instance_id')}")
        require(similarities[0] >= 0.90 and confidences[0] >= 0.70, f"confirmed_single_frame_quality:{row.get('instance_id')}")
    else:
        require(median(similarities) >= float(config.get("min_text_similarity") or 0.62), f"confirmed_similarity:{row.get('instance_id')}")
        require(median(confidences) >= float(config.get("min_median_ocr_confidence") or 0.24), f"confirmed_confidence:{row.get('instance_id')}")
    for item in observations:
        bbox = item.get("normalized_bbox") if isinstance(item, Mapping) else None
        require(isinstance(bbox, list) and len(bbox) == 4, f"confirmed_bbox:{row.get('instance_id')}")
        require(0.0 <= float(bbox[0]) < float(bbox[2]) <= 1.0, f"confirmed_bbox_x:{row.get('instance_id')}")
        require(0.0 <= float(bbox[1]) < float(bbox[3]) <= 1.0, f"confirmed_bbox_y:{row.get('instance_id')}")
        require(str(item.get("method") or "") in {"full_frame_ocr", "source_pixel_local_crop_ocr"}, f"confirmed_method:{row.get('instance_id')}")


def validate_absent(row: Mapping[str, Any], protected_ids: set[str]) -> None:
    require(row.get("semantic_basis") == "represented_by_protected_composite_visual_layer", f"absent_basis:{row.get('instance_id')}")
    composite = row.get("protected_composite") if isinstance(row.get("protected_composite"), Mapping) else {}
    require(str(composite.get("protected_instance_id") or "") in protected_ids, f"absent_composite:{row.get('instance_id')}")
    require(str(row.get("instance_id") or "") in [str(v) for v in composite.get("source_instance_ids") or []], f"absent_source_membership:{row.get('instance_id')}")
    require(not (row.get("semantic_observations") or []), f"absent_semantic_geometry:{row.get('instance_id')}")


def validate_unresolved(row: Mapping[str, Any]) -> None:
    prior = row.get("search_prior") if isinstance(row.get("search_prior"), Mapping) else {}
    require(prior.get("probe_frames"), f"unresolved_not_probed:{row.get('instance_id')}")
    evidence = row.get("probe_evidence") if isinstance(row.get("probe_evidence"), Mapping) else {}
    require(evidence.get("reasons"), f"unresolved_reasons:{row.get('instance_id')}")


def validate(root: Path, coverage_path: Path, output_path: Path) -> dict[str, Any]:
    authority_path = root / CURRENT_AUTHORITY
    require(authority_path.is_file(), f"authority_missing:{authority_path}")
    require(coverage_path.is_file(), f"coverage_missing:{coverage_path}")
    authority = load_json(authority_path)
    coverage = load_json(coverage_path)
    require(coverage.get("ok") is True and coverage.get("task_id") == TASK_ID, "coverage_header")
    expected_hash = canonical_sha256({k: v for k, v in coverage.items() if k != "semantic_sha256"})
    require(coverage.get("semantic_sha256") == expected_hash, "semantic_sha256")

    policy = coverage.get("policy") if isinstance(coverage.get("policy"), Mapping) else {}
    for key in (
        "source_pixel_windows_are_search_priors_only",
        "geometry_only_cannot_confirm_semantics",
        "negative_ocr_alone_cannot_prove_absence",
        "protected_composite_can_reconcile_redundant_structural_rows",
    ):
        require(policy.get(key) is True, f"policy:{key}")
    require(policy.get("transcript_timing_authority") is False, "policy:transcript_timing_authority")
    require(policy.get("per_cue_hardcoded_overrides") is False, "policy:per_cue_hardcoded_overrides")
    require(policy.get("resolve_modified") is False, "policy:resolve_modified")
    require(policy.get("repair_rollout_authorized") is False, "policy:repair_rollout_authorized")

    authority_excluded = {
        str(row.get("instance_id") or "")
        for row in authority.get("instances") or []
        if isinstance(row, Mapping) and row.get("presence_status") in {"source_unresolved", "source_not_evaluated"}
    }
    protected_ids = {
        str(row.get("instance_id") or "")
        for row in authority.get("instances") or []
        if isinstance(row, Mapping) and row.get("presence_status") == "protected_existing"
    }
    require(len(authority_excluded) == EXPECTED_EXCLUDED, "authority_excluded_count")

    rows = coverage.get("coverage")
    require(isinstance(rows, list) and len(rows) == EXPECTED_EXCLUDED, "coverage_count")
    ids = [str(row.get("instance_id") or "") for row in rows if isinstance(row, Mapping)]
    require(len(ids) == len(set(ids)) == EXPECTED_EXCLUDED, "coverage_identity")
    require(set(ids) == authority_excluded, "coverage_exact_excluded_set")

    config = coverage.get("configuration") if isinstance(coverage.get("configuration"), Mapping) else {}
    counts = {name: 0 for name in ("source_confirmed", "source_absent_or_nonsemantic", "source_unresolved", "source_not_evaluated")}
    for row in rows:
        require(isinstance(row, Mapping), "coverage_row_type")
        instance_id = str(row.get("instance_id") or "")
        require(row.get("transcript_timing_authority") is False, f"row_transcript_timing:{instance_id}")
        prior = row.get("search_prior") if isinstance(row.get("search_prior"), Mapping) else {}
        require(prior.get("authority") == "source_pixel_visibility_only", f"row_search_authority:{instance_id}")
        require(prior.get("cue_or_transcript_window_used_as_authority") is False, f"row_cue_authority:{instance_id}")
        status = str(row.get("coverage_status") or "")
        require(status in counts, f"coverage_status:{instance_id}:{status}")
        counts[status] += 1
        if status == "source_confirmed":
            validate_confirmed(row, config)
        elif status == "source_absent_or_nonsemantic":
            validate_absent(row, protected_ids)
        elif status == "source_unresolved":
            validate_unresolved(row)
        else:
            raise ValidationError(f"not_evaluated_forbidden:{instance_id}")

    summary = coverage.get("summary") if isinstance(coverage.get("summary"), Mapping) else {}
    require(int(summary.get("evaluated_excluded_instances") or 0) == EXPECTED_EXCLUDED, "summary_evaluated")
    require(int(summary.get("source_confirmed_instances") or 0) == counts["source_confirmed"], "summary_confirmed")
    require(int(summary.get("source_absent_or_nonsemantic_instances") or 0) == counts["source_absent_or_nonsemantic"], "summary_absent")
    require(int(summary.get("source_unresolved_instances") or 0) == counts["source_unresolved"], "summary_unresolved")
    require(int(summary.get("source_not_evaluated_instances") or 0) == 0, "summary_not_evaluated")
    require(sum(counts.values()) == EXPECTED_EXCLUDED, "summary_partition")
    require(summary.get("resolve_modified") is False, "summary_resolve")
    require(summary.get("repair_rollout_authorized") is False, "summary_rollout")

    result = {
        "task_id": TASK_ID,
        "ok": True,
        "coverage_sha256": coverage.get("semantic_sha256"),
        "checks": {
            "evaluated_excluded_instances": EXPECTED_EXCLUDED,
            "source_confirmed_instances": counts["source_confirmed"],
            "source_absent_or_nonsemantic_instances": counts["source_absent_or_nonsemantic"],
            "source_unresolved_instances": counts["source_unresolved"],
            "source_not_evaluated_instances": 0,
            "exact_excluded_set": True,
            "transcript_timing_authority": False,
            "geometry_only_semantic_promotion": False,
            "negative_ocr_absence_promotion": False,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
    }
    write_json(output_path, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    coverage = args.coverage.resolve() if args.coverage else root / DEFAULT_COVERAGE
    output = args.output.resolve() if args.output else root / DEFAULT_OUTPUT
    try:
        result = validate(root, coverage, output)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {TASK_ID}: {type(exc).__name__}: {exc}")
        return 1
    checks = result["checks"]
    print(
        f"PASS {TASK_ID}: evaluated={checks['evaluated_excluded_instances']} "
        f"confirmed={checks['source_confirmed_instances']} "
        f"absent_or_nonsemantic={checks['source_absent_or_nonsemantic_instances']} "
        f"unresolved={checks['source_unresolved_instances']} not_evaluated=0"
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
