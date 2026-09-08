#!/usr/bin/env python3
"""Validate Step 3E unresolved source classification V1."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

TASK_ID = "DZSQH7AUHJT_STEP_3E_UNRESOLVED_SOURCE_CLASSIFICATION_V1"
DEFAULT_AUTHORITY = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_SOURCE_CLASSIFICATION_V1/unresolved_source_classification_v1.json")
DEFAULT_OUTPUT = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_SOURCE_CLASSIFICATION_V1/unresolved_source_classification_validation.json")
EXPECTED_EVALUATED = 22
EXPECTED_STRUCTURAL = 117
EXPECTED_PHYSICAL = 114


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


def exact_int(summary: Mapping[str, Any], key: str, expected: int, code: str) -> None:
    require(key in summary, code)
    value = summary[key]
    require(isinstance(value, int) and not isinstance(value, bool) and value == expected, code)


def validate(authority: Mapping[str, Any]) -> dict[str, bool]:
    require(authority.get("task_id") == TASK_ID, "task_id")
    require(authority.get("ok") is True, "authority_ok")
    policy = authority.get("policy") or {}
    require(policy.get("transcript_timing_authority") is False, "transcript_timing")
    require(policy.get("geometry_only_semantic_promotion") is False, "geometry_promotion")
    require(policy.get("negative_ocr_promoted_to_absence") is False, "negative_absence")
    require(policy.get("sampled_negative_ocr_can_prove_absence") is False, "sampled_absence")
    require(policy.get("source_not_materialized_requires_full_window_multi_signal_absence_gate") is True, "absence_gate_policy")
    require(policy.get("resolve_modified") is False, "resolve_modified")
    require(policy.get("repair_rollout_authorized") is False, "rollout")

    rows = authority.get("classifications") or []
    require(isinstance(rows, list) and len(rows) == EXPECTED_EVALUATED, "classification_count")
    ids = [str(row.get("instance_id") or "") for row in rows if isinstance(row, Mapping)]
    require(len(ids) == EXPECTED_EVALUATED and len(set(ids)) == EXPECTED_EVALUATED and all(ids), "classification_ids")

    allowed = {
        "source_semantic_track_recovered",
        "source_semantic_anchor_only",
        "source_compound_member_represented",
        "source_not_materialized",
        "source_still_unresolved",
    }
    counts = {key: 0 for key in allowed}
    for row in rows:
        require(isinstance(row, Mapping), "classification_row")
        classification = str(row.get("classification") or "")
        require(classification in allowed, f"classification:{classification}")
        counts[classification] += 1
        require(row.get("transcript_timing_authority") is False, "row_transcript")
        require(row.get("geometry_only_semantic_promotion") is False, "row_geometry")
        require(row.get("negative_ocr_promoted_to_absence") is False, "row_negative_absence")
        require(row.get("resolve_application_authorized") is False, "row_rollout")

        if classification == "source_semantic_track_recovered":
            require(row.get("source_materialized") is True, "track_materialized")
            anchor = row.get("exact_source_ocr_anchor") or {}
            require(float(anchor.get("confidence") or 0.0) >= 0.90, "track_anchor_confidence")
            tracking = row.get("source_pixel_tracking") or {}
            require(int(tracking.get("strong_support") or 0) >= 2, "track_support")
            require(isinstance(row.get("visual_window"), list) and len(row["visual_window"]) == 2, "track_window")
        elif classification == "source_semantic_anchor_only":
            require(row.get("source_materialized") is True, "anchor_materialized")
            require(row.get("timing_status") == "source_identity_confirmed_duration_unresolved", "anchor_timing")
            anchor = row.get("exact_source_ocr_anchor") or {}
            require(float(anchor.get("confidence") or 0.0) >= 0.90, "anchor_confidence")
        elif classification == "source_compound_member_represented":
            require(row.get("source_materialized") is True, "compound_materialized")
            membership = row.get("compound_membership") or {}
            require(row.get("instance_id") in (membership.get("member_ids") or []), "compound_member")
            require(membership.get("identity_rule") == "exact_compact_adjacent_concatenation", "compound_identity")
            require(len(membership.get("source_frames") or []) >= 2, "compound_frames")
        elif classification == "source_not_materialized":
            require(row.get("source_materialized") is False, "absence_materialized")
            evidence = row.get("absence_evidence") or {}
            require(evidence.get("full_window_semantic_scan") is True, "absence_full_scan")
            require(evidence.get("neighbor_sequence_closed") is True, "absence_sequence")
            require(type(evidence.get("unexplained_text_components")) is int and evidence["unexplained_text_components"] == 0, "absence_components")
            require(type(evidence.get("semantic_hits")) is int and evidence["semantic_hits"] == 0, "absence_semantics")
        elif classification == "source_still_unresolved":
            require(row.get("source_materialized") is None, "unresolved_materialized")
            require(row.get("timing_status") == "unresolved", "unresolved_timing")

    summary = authority.get("summary") or {}
    exact_int(summary, "evaluated_remaining", EXPECTED_EVALUATED, "summary_evaluated")
    exact_int(summary, "source_semantic_track_recovered", counts["source_semantic_track_recovered"], "summary_track")
    exact_int(summary, "source_semantic_anchor_only", counts["source_semantic_anchor_only"], "summary_anchor")
    exact_int(summary, "source_compound_member_represented", counts["source_compound_member_represented"], "summary_compound")
    exact_int(summary, "source_not_materialized", counts["source_not_materialized"], "summary_not_materialized")
    exact_int(summary, "source_still_unresolved", counts["source_still_unresolved"], "summary_unresolved")
    exact_int(summary, "source_absent_claims", counts["source_not_materialized"], "summary_absent")
    exact_int(summary, "prior_visual_companion_recovered", 1, "summary_companion")
    exact_int(summary, "structural_total", EXPECTED_STRUCTURAL, "summary_structural")
    exact_int(summary, "physical_textplus_before_final_merge", EXPECTED_PHYSICAL, "summary_physical")
    require(summary.get("resolve_modified") is False, "summary_resolve")
    require(summary.get("repair_rollout_authorized") is False, "summary_rollout")

    require(counts["source_not_materialized"] == 0, "unexpected_absence")
    require(counts["source_semantic_track_recovered"] + counts["source_semantic_anchor_only"] + counts["source_compound_member_represented"] > 0, "no_progress")
    return {
        "authority_ok": True,
        "all_rows_evaluated": True,
        "no_absence_without_full_window_audit": True,
        "negative_ocr_not_absence": True,
        "positive_source_classification_present": True,
        "resolve_untouched": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--authority", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    root = args.root.resolve()
    authority_path = (args.authority or (root / DEFAULT_AUTHORITY)).resolve()
    output_path = (args.output or (root / DEFAULT_OUTPUT)).resolve()
    authority = load_json(authority_path)
    checks = validate(authority)
    expected_semantic = str(authority.get("semantic_sha256") or "")
    actual_semantic = canonical_sha256({k: v for k, v in authority.items() if k != "semantic_sha256"})
    require(expected_semantic == actual_semantic, "semantic_sha256")
    result = {
        "task_id": TASK_ID,
        "ok": True,
        "authority_path": str(authority_path.relative_to(root)),
        "authority_sha256": sha256(authority_path),
        "semantic_sha256": actual_semantic,
        "checks": checks,
        "summary": dict(authority.get("summary") or {}),
    }
    write_json(output_path, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
