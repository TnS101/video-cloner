#!/usr/bin/env python3
"""Validate Step 3E unresolved visual-layer recovery authority V1."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

TASK_ID = "DZSQH7AUHJT_STEP_3E_UNRESOLVED_VISUAL_LAYER_RECOVERY_V1"
EXPECTED_UNRESOLVED = 23
EXPECTED_STRUCTURAL = 117
EXPECTED_PHYSICAL = 114
ALLOWED = {
    "source_semantic_recovered",
    "source_compound_semantic_recovered",
    "source_visual_companion_recovered",
    "source_unresolved_after_recovery",
}
DEFAULT_AUTHORITY = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_VISUAL_LAYER_RECOVERY_V1/unresolved_visual_layer_recovery_v1.json")
DEFAULT_OUTPUT = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_VISUAL_LAYER_RECOVERY_V1/unresolved_visual_layer_recovery_validation.json")


class ValidationError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValidationError(code)


def require_exact_int_field(mapping: Mapping[str, Any], key: str, expected: int, code: str) -> None:
    value = mapping.get(key)
    require(key in mapping and type(value) is int and value == expected, code)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"expected_object:{path}")
    return value


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, path)


def validate(authority: Mapping[str, Any]) -> dict[str, Any]:
    require(authority.get("task_id") == TASK_ID, "task_id")
    require(authority.get("ok") is True, "authority_ok")
    policy = authority.get("policy") if isinstance(authority.get("policy"), Mapping) else {}
    require(policy.get("transcript_timing_authority") is False, "transcript_timing")
    require(policy.get("geometry_only_semantic_promotion") is False, "geometry_promotion")
    require(policy.get("negative_ocr_promoted_to_absence") is False, "negative_absence")
    require(policy.get("per_cue_hardcoded_overrides") is False, "per_cue")
    require(policy.get("screenshot_specific_overrides") is False, "screenshot")
    require(policy.get("resolve_modified") is False, "resolve_modified")
    require(policy.get("repair_rollout_authorized") is False, "rollout")

    rows = [row for row in authority.get("classifications") or [] if isinstance(row, Mapping)]
    require(len(rows) == EXPECTED_UNRESOLVED, "classification_count")
    ids = [str(row.get("instance_id") or "") for row in rows]
    require(len(set(ids)) == EXPECTED_UNRESOLVED and all(ids), "classification_ids")

    counts = {name: 0 for name in ALLOWED}
    for row in rows:
        classification = str(row.get("classification") or "")
        require(classification in ALLOWED, f"classification:{classification}")
        counts[classification] += 1
        require(row.get("transcript_timing_authority") is False, f"row_transcript:{row.get('instance_id')}")
        require(row.get("resolve_application_authorized") is False, f"row_resolve:{row.get('instance_id')}")
        if classification == "source_semantic_recovered":
            require(int(row.get("support") or 0) >= 2, f"semantic_support:{row.get('instance_id')}")
            require(len(set(row.get("support_frames") or [])) >= 2, f"semantic_frames:{row.get('instance_id')}")
            require(row.get("geometry_partitioned_from_compound") is False, f"semantic_partition:{row.get('instance_id')}")
        elif classification == "source_compound_semantic_recovered":
            require(int(row.get("support") or 0) >= 2, f"compound_support:{row.get('instance_id')}")
            require(row.get("geometry_partitioned_from_compound") is True, f"compound_partition:{row.get('instance_id')}")
            members = row.get("member_instance_ids") or []
            require(2 <= len(members) <= 3 and row.get("instance_id") in members, f"compound_members:{row.get('instance_id')}")
            require(all(isinstance(obs.get("full_compound_normalized_bbox"), list) for obs in row.get("observations") or []), f"compound_full_bbox:{row.get('instance_id')}")
        elif classification == "source_visual_companion_recovered":
            require(row.get("semantic_promotion") is False, f"companion_semantic:{row.get('instance_id')}")
            require(str(row.get("basis") or "") == "accepted_v4_visual_only_source_template_multiframe", f"companion_basis:{row.get('instance_id')}")
            require(int(row.get("support") or 0) >= 3, f"companion_support:{row.get('instance_id')}")
            require(float(row.get("peak_match_score") or 0.0) >= 0.70, f"companion_peak:{row.get('instance_id')}")
            require(float(row.get("prototype_self_score") or 0.0) >= 0.80, f"companion_self:{row.get('instance_id')}")
            require(str(row.get("prototype_id") or ""), f"companion_prototype:{row.get('instance_id')}")
            require(isinstance(row.get("frame_path"), list) and len(row["frame_path"]) >= 3, f"companion_path:{row.get('instance_id')}")
        else:
            require(row.get("negative_ocr_promoted_to_absence") is False, f"unresolved_absence:{row.get('instance_id')}")
            require(row.get("semantic_promotion") is False, f"unresolved_semantic:{row.get('instance_id')}")

    summary = authority.get("summary") if isinstance(authority.get("summary"), Mapping) else {}
    require(int(summary.get("evaluated_unresolved") or 0) == EXPECTED_UNRESOLVED, "summary_evaluated")
    require(int(summary.get("source_visual_companion_recovered") or 0) >= 1, "summary_companion")
    require_exact_int_field(summary, "source_absent_claims", 0, "summary_absent")
    require(int(summary.get("structural_total") or 0) == EXPECTED_STRUCTURAL, "summary_structural")
    require(int(summary.get("physical_textplus_before_merge") or 0) == EXPECTED_PHYSICAL, "summary_physical")
    require(summary.get("resolve_modified") is False, "summary_resolve")
    require(summary.get("repair_rollout_authorized") is False, "summary_rollout")
    require(sum(counts.values()) == EXPECTED_UNRESOLVED, "summary_partition")

    semantic = str(authority.get("semantic_sha256") or "")
    require(len(semantic) == 64, "semantic_sha")
    expected_semantic = canonical_sha256({k: v for k, v in authority.items() if k != "semantic_sha256"})
    require(semantic == expected_semantic, "semantic_sha_mismatch")

    return {
        "task_id": TASK_ID,
        "ok": True,
        "checks": {
            "evaluated_23": True,
            "classification_partition_valid": True,
            "semantic_recovery_multiframe_only": True,
            "compound_geometry_partitioned": True,
            "visual_companion_accepted_prototype_only": True,
            "negative_ocr_not_absence": True,
            "geometry_only_semantic_promotion": False,
            "transcript_timing_authority": False,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
        "summary": dict(summary),
        "semantic_sha256": semantic,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--authority", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    root = args.root.resolve()
    authority_path = (args.authority or (root / DEFAULT_AUTHORITY)).resolve()
    output = (args.output or (root / DEFAULT_OUTPUT)).resolve()
    result = validate(load_json(authority_path))
    write_json(output, result)
    print(json.dumps(result["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
