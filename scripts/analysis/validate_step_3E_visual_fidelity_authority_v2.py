#!/usr/bin/env python3
"""Validate Step 3E visual-fidelity authority V2."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

TASK_ID = "DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_AUTHORITY_V2"
AUTHORITY = Path("artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_AUTHORITY_V2/visual_fidelity_authority_v2.json")
DEFAULT_OUTPUT = Path("artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_AUTHORITY_V2/visual_fidelity_authority_validation.json")
EXPECTED_TOTAL = 117
EXPECTED_PHYSICAL = 114
EXPECTED_REPAIR = 74
EXPECTED_PROTECTED = 17
EXPECTED_UNRESOLVED = 23
EXPECTED_REMOVED = 3


class ValidationError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValidationError(code)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"object:{path}")
    return value


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def validate(root: Path, authority_path: Path, output_path: Path) -> dict[str, Any]:
    doc = load_json(authority_path)
    require(doc.get("task_id") == TASK_ID, "task_id")
    require(doc.get("ok") is True, "authority_ok")
    expected_hash = canonical_sha256({k: v for k, v in doc.items() if k != "semantic_sha256"})
    require(doc.get("semantic_sha256") == expected_hash, "semantic_sha256")

    policy = doc.get("policy") if isinstance(doc.get("policy"), Mapping) else {}
    required_false = [
        "transcript_timing_authority",
        "per_cue_hardcoded_overrides",
        "screenshot_specific_overrides",
        "geometry_only_semantic_promotion",
        "detector_score_controls_opacity",
        "resolve_modified",
        "repair_rollout_authorized",
    ]
    for key in required_false:
        require(policy.get(key) is False, f"policy_false:{key}")
    for key in ["short_tokens_require_exact_semantic_anchor", "static_motion_is_default", "weak_family_font_calibration_must_fallback", "source_case_is_visual_style", "occlusion_foreground_must_survive_caption_mutation"]:
        require(policy.get(key) is True, f"policy_true:{key}")

    inventory = doc.get("inventory") or {}
    require(int(inventory.get("structural_total") or 0) == EXPECTED_TOTAL, "structural_total")
    require(int(inventory.get("physical_textplus") or 0) == EXPECTED_PHYSICAL, "physical_textplus")
    require(len(inventory.get("repair_ready") or []) == EXPECTED_REPAIR, "repair_inventory")
    require(len(inventory.get("protected") or []) == EXPECTED_PROTECTED, "protected_inventory")
    require(len(inventory.get("unresolved_preserved") or []) == EXPECTED_UNRESOLVED, "unresolved_inventory")
    require(len(inventory.get("composite_structural_removed") or []) == EXPECTED_REMOVED, "removed_inventory")

    reanchor = doc.get("strict_reanchor") or {}
    require(int(reanchor.get("required") or 0) >= 1, "reanchor_not_exercised")
    require(int(reanchor.get("reanchored") or 0) == int(reanchor.get("required") or 0), "reanchor_incomplete")
    require(not (reanchor.get("failures") or []), "reanchor_failures")

    repair = doc.get("repair_instances") or []
    require(len(repair) == EXPECTED_REPAIR, "repair_count")
    ids = [str(row.get("instance_id") or "") for row in repair]
    require(len(ids) == len(set(ids)), "repair_duplicate")
    for row in repair:
        require(row.get("authorized") is True, f"repair_authorized:{row.get('instance_id')}")
        require(row.get("identity_status") == "strict_source_semantic_confirmed", f"identity:{row.get('instance_id')}")
        require(row.get("transcript_timing_authority") is False, f"transcript:{row.get('instance_id')}")
        window = row.get("visual_window") or []
        path = row.get("frame_path") or []
        require(len(window) == 2 and int(window[1]) > int(window[0]), f"window:{row.get('instance_id')}")
        require([int(x["timeline_frame"]) for x in path] == list(range(int(window[0]), int(window[1]))), f"dense_path:{row.get('instance_id')}")
        motion = row.get("motion") or {}
        if motion.get("position_model") != "source_static_hold":
            require(float(motion.get("displacement_ref_px") or 0.0) >= max(8.0, float(motion.get("median_bbox_height_ref_px") or 0.0) * 0.35) or motion.get("exit_motion") is True, f"weak_motion:{row.get('instance_id')}")
        if motion.get("size_model") != "source_static_hold":
            require(float(motion.get("size_change_ref_px") or 0.0) >= max(4.0, float(motion.get("median_bbox_height_ref_px") or 0.0) * 0.30), f"weak_size:{row.get('instance_id')}")
        case = row.get("text_case") or {}
        if case.get("apply"):
            import re
            compact = lambda v: re.sub(r"[^a-z0-9]+", "", str(v or "").casefold())
            require(compact(case.get("text")) == compact(row.get("canonical_text")), f"case_semantics:{row.get('instance_id')}")
        size = row.get("size") or {}
        if str(size.get("model_source") or "").startswith("family"):
            # Family-specific models are only legal when supported by >=3 V4 samples.
            families = doc.get("font_render_calibration_v2", {}).get("families") or []
            match = next((f for f in families if f.get("font_family") == size.get("font_family") and f.get("font_style") == size.get("font_style")), None)
            require(match is not None and int(match.get("sample_count") or 0) >= 3, f"weak_family_used:{row.get('instance_id')}")

    protected = doc.get("protected_motion_review") or []
    require(len(protected) == EXPECTED_PROTECTED, "protected_motion_count")
    require(all(row.get("authorized") is True for row in protected), "protected_motion_missing")
    require(any((row.get("motion") or {}).get("exit_motion") is True for row in protected), "source_exit_not_detected")

    groups = doc.get("layout_groups") or []
    for group in groups:
        members = group.get("member_instance_ids") or []
        require(len(members) >= 2 and len(members) == len(set(members)), f"layout_group:{group.get('group_id')}")
        require(group.get("transcript_timing_authority") is False, f"layout_transcript:{group.get('group_id')}")

    occ = doc.get("occlusion_contract") or {}
    require(occ.get("enabled") is True, "occlusion_disabled")
    require(int(occ.get("asset_span_count") or 0) >= 1, "occlusion_span")
    require(int(occ.get("complete_asset_span_count") or 0) == int(occ.get("asset_span_count") or 0), "occlusion_incomplete")
    require(occ.get("required_layer_order") == "foreground_rgba_above_textplus", "occlusion_layer_order")
    require(occ.get("persistent_readback_required") is True, "occlusion_readback")

    for rel, info in (doc.get("inputs") or {}).items():
        if rel == "source_video":
            path = root / Path(str(info.get("path") or "").replace("\\", "/"))
        else:
            path = root / Path(str(info.get("path") or rel).replace("\\", "/"))
        require(path.is_file(), f"input_missing:{rel}")
        require(raw_sha256(path) == str(info.get("sha256") or ""), f"input_sha:{rel}")

    summary = doc.get("summary") or {}
    require(int(summary.get("repair_instances") or 0) == EXPECTED_REPAIR, "summary_repair")
    require(int(summary.get("protected_instances") or 0) == EXPECTED_PROTECTED, "summary_protected")
    require(int(summary.get("strict_reanchor_failures") or 0) == 0, "summary_reanchor")
    require(int(summary.get("detected_exit_motion_instances") or 0) >= 1, "summary_exit")
    require(summary.get("resolve_modified") is False, "summary_resolve")
    require(summary.get("repair_rollout_authorized") is False, "summary_rollout")

    result = {
        "task_id": TASK_ID,
        "ok": True,
        "authority_path": str(authority_path.relative_to(root) if authority_path.is_relative_to(root) else authority_path),
        "authority_sha256": raw_sha256(authority_path),
        "checks": {
            "semantic_hash": True,
            "source_only_timing": True,
            "strict_short_reanchor": True,
            "motion_hysteresis": True,
            "dual_axis_font_calibration": True,
            "source_case_contract": True,
            "layout_groups": True,
            "occlusion_foreground_contract": True,
            "resolve_not_modified": True,
            "rollout_locked": True,
        },
        "summary": summary,
    }
    write_json(output_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--authority", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    root = args.root.resolve()
    authority = (root / AUTHORITY) if args.authority is None else args.authority.resolve()
    output = (root / DEFAULT_OUTPUT) if args.output is None else args.output.resolve()
    result = validate(root, authority, output)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
