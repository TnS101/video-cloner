#!/usr/bin/env python3
"""Validate the final Step 3E unresolved-nine visual audit V1."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

TASK_ID = "DZSQH7AUHJT_STEP_3E_FINAL_UNRESOLVED9_VISUAL_AUDIT_V1"
DEFAULT_AUTHORITY = Path("artifacts/DZSQH7AUHJT_STEP_3E_FINAL_UNRESOLVED9_VISUAL_AUDIT_V1/final_unresolved9_visual_audit_v1.json")
DEFAULT_OUTPUT = Path("artifacts/DZSQH7AUHJT_STEP_3E_FINAL_UNRESOLVED9_VISUAL_AUDIT_V1/final_unresolved9_visual_audit_validation.json")
EXPECTED_RESIDUAL = 9
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
    require(type(value) is int and value == expected, code)


def validate(authority: Mapping[str, Any]) -> dict[str, bool]:
    require(authority.get("task_id") == TASK_ID, "task_id")
    require(authority.get("ok") is True, "authority_ok")
    policy = authority.get("policy") or {}
    require(policy.get("all_residual_rows_receive_full_window_ocr_scan") is True, "full_scan_policy")
    require(policy.get("negative_ocr_promoted_to_absence") is False, "negative_absence")
    require(policy.get("source_absence_claims_allowed") is False, "absence_policy")
    require(policy.get("geometry_only_semantic_promotion") is False, "geometry_promotion")
    require(policy.get("transcript_timing_authority") is False, "transcript_timing")
    require(policy.get("semantic_recovery_requires_source_pixel_continuity") is True, "semantic_continuity")
    require(policy.get("sparse_low_confidence_short_semantic_anchors_are_quarantined") is True, "quarantine_policy")
    require(policy.get("per_cue_hardcoded_overrides") is False, "cue_overrides")
    require(policy.get("screenshot_specific_overrides") is False, "screenshot_overrides")
    require(policy.get("resolve_modified") is False, "resolve_modified")
    require(policy.get("repair_rollout_authorized") is False, "rollout")
    require(policy.get("offline_recovery_stops_after_this_boundary") is True, "stop_boundary")

    rows = authority.get("audits") or []
    require(isinstance(rows, list) and len(rows) == EXPECTED_RESIDUAL, "audit_count")
    ids = [str(x.get("instance_id") or "") for x in rows if isinstance(x, Mapping)]
    require(len(ids) == EXPECTED_RESIDUAL and len(set(ids)) == EXPECTED_RESIDUAL and all(ids), "audit_ids")

    allowed = {
        "recovered_semantic",
        "recovered_visual_companion",
        "represented_by_existing_visual_layer",
        "unresolved_after_full_visual_audit",
    }
    counts = {key: 0 for key in allowed}
    for row in rows:
        require(isinstance(row, Mapping), "audit_row")
        classification = str(row.get("classification") or "")
        require(classification in allowed, f"classification:{classification}")
        counts[classification] += 1
        require(row.get("full_window_ocr_scan") is True, "row_full_scan")
        window = row.get("audit_window")
        require(isinstance(window, list) and len(window) == 2 and int(window[0]) < int(window[1]), "row_window")
        require(type(row.get("frames_scanned")) is int and row["frames_scanned"] == int(window[1]) - int(window[0]), "row_frames")
        require(row.get("transcript_timing_authority") is False, "row_transcript")
        require(row.get("geometry_only_semantic_promotion") is False, "row_geometry")
        require(row.get("negative_ocr_promoted_to_absence") is False, "row_negative_absence")
        require(row.get("source_absence_claimed") is False, "row_absence")
        require(row.get("resolve_application_authorized") is False, "row_rollout")
        if classification == "recovered_semantic":
            require(row.get("source_materialized") is True, "semantic_materialized")
            require(isinstance(row.get("semantic_observations"), list) and row["semantic_observations"], "semantic_observations")
            tracking = row.get("source_pixel_tracking") or {}
            require(type(tracking.get("strong_support")) is int and tracking["strong_support"] >= 2, "semantic_tracking")
            require(isinstance(row.get("visual_window"), list) and len(row["visual_window"]) == 2, "semantic_window")
        elif classification == "represented_by_existing_visual_layer":
            require(row.get("source_materialized") is True, "represented_materialized")
            require(isinstance(row.get("compound_observations"), list) and row["compound_observations"], "represented_observations")
        elif classification == "unresolved_after_full_visual_audit":
            require(row.get("source_materialized") is None, "unresolved_materialized")
            require(row.get("timing_status") == "unresolved", "unresolved_timing")
            evidence = row.get("audit_evidence") or {}
            require(evidence.get("negative_scan_is_not_absence") is True, "unresolved_negative_policy")

    quarantine = authority.get("repair_authority_quarantine") or []
    require(isinstance(quarantine, list) and len(quarantine) >= 1, "quarantine_count")
    qids = []
    for row in quarantine:
        require(isinstance(row, Mapping), "quarantine_row")
        iid = str(row.get("instance_id") or "")
        require(iid, "quarantine_id")
        qids.append(iid)
        require(float(row.get("anchor_confidence") or 1.0) < 0.85, "quarantine_confidence")
        require(row.get("reason") == "short_exact_identity_has_only_sparse_low_confidence_ocr_anchor", "quarantine_reason")
        require(row.get("cue_specific_rule") is False, "quarantine_cue_rule")
        require(row.get("final_rollout_action") == "remove_or_do_not_materialize_semantic_textplus_until_multiframe_semantics_exist", "quarantine_action")
    require(len(qids) == len(set(qids)), "quarantine_unique")

    summary = authority.get("summary") or {}
    exact_int(summary, "evaluated_residual", EXPECTED_RESIDUAL, "summary_evaluated")
    exact_int(summary, "recovered_semantic", counts["recovered_semantic"], "summary_semantic")
    exact_int(summary, "recovered_visual_companion", counts["recovered_visual_companion"], "summary_companion")
    exact_int(summary, "represented_by_existing_visual_layer", counts["represented_by_existing_visual_layer"], "summary_represented")
    exact_int(summary, "unresolved_after_full_visual_audit", counts["unresolved_after_full_visual_audit"], "summary_unresolved")
    exact_int(summary, "source_absent_claims", 0, "summary_absent")
    exact_int(summary, "sparse_short_anchor_quarantines", len(quarantine), "summary_quarantine")
    exact_int(summary, "prior_visual_companion_recovered", 1, "summary_prior_companion")
    exact_int(summary, "structural_total", EXPECTED_STRUCTURAL, "summary_structural")
    exact_int(summary, "physical_textplus_before_final_rollout", EXPECTED_PHYSICAL, "summary_physical")
    require(summary.get("resolve_modified") is False, "summary_resolve")
    require(summary.get("repair_rollout_authorized") is False, "summary_rollout")
    require(sum(counts.values()) == EXPECTED_RESIDUAL, "summary_partition")

    return {
        "authority_ok": True,
        "all_nine_full_window_audited": True,
        "no_source_absence_claims": True,
        "semantic_recovery_requires_pixel_continuity": True,
        "unsafe_sparse_short_anchors_quarantined": True,
        "residual_ambiguity_explicit": True,
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
