#!/usr/bin/env python3
"""Validate the Step 3D visual-first authority lock V2."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_AUTHORITY_LOCK_V2"
EXPECTED_GROUP_IDS = (
    "vf_group_01_nineteen_identity",
    "vf_group_02_already_decorated",
    "vf_group_03_stakes_are_high",
    "vf_group_04_knows_market_persistence",
    "vf_group_05_decorated_know",
    "vf_group_06_buildings_blocks_builders",
    "vf_group_07_something_motion",
)
EXPECTED_TOKEN_IDS = {
    "vf_01_nineteen",
    "vf_02_decorative_glyph",
    "vf_02_already",
    "vf_03_stakes",
    "vf_03_are",
    "vf_03_high",
    "vf_04_that",
    "vf_04_knows",
    "vf_04_market",
    "vf_04_back",
    "vf_04_their",
    "vf_05_decorative_glyph",
    "vf_05_know",
    "vf_06_buildings",
    "vf_06_blocks",
    "vf_06_builders",
    "vf_07_something",
}
FORBIDDEN_PLACEHOLDERS = (
    "source_pixels_define",
    "shared_with_group",
    "unresolved",
    "manual_source_review_required",
)


class ValidationError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValidationError(code)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate(output_dir: Path) -> dict[str, Any]:
    manifest_path = output_dir / "visual_authority_lock_v2.json"
    summary_path = output_dir / "LOCK_SUMMARY.md"
    require(manifest_path.is_file(), "manifest_missing")
    require(summary_path.is_file(), "summary_missing")
    manifest = load_json(manifest_path)
    require(manifest.get("task_id") == TASK_ID, "task_id_mismatch")
    require(manifest.get("ok") is True, "manifest_not_ok")
    summary = manifest.get("summary")
    require(isinstance(summary, dict), "summary_invalid")
    require(summary.get("group_count") == 7, "group_count_invalid")
    require(summary.get("visual_token_count") == 17, "token_count_invalid")
    require(summary.get("visual_only_component_count") == 2, "visual_only_count_invalid")
    require(summary.get("unresolved_component_count") == 0, "unresolved_components_present")
    require(summary.get("placeholder_count") == 0, "placeholders_present")
    require(summary.get("transcript_timing_promoted_count") == 0, "transcript_timing_promoted")
    require(summary.get("resolve_modified") is False, "resolve_modified")
    require(summary.get("seven_window_resolve_pilot_authorized") is True, "pilot_not_authorized")
    require(summary.get("full_rollout_authorized") is False, "full_rollout_authorized")

    groups = manifest.get("groups")
    require(isinstance(groups, list), "groups_invalid")
    require(tuple(group.get("group_id") for group in groups) == EXPECTED_GROUP_IDS, "group_order_invalid")
    tokens: dict[str, dict[str, Any]] = {}
    for group in groups:
        require(group.get("status") == "locked_for_seven_window_resolve_pilot", f"group_not_locked:{group.get('group_id')}")
        artifacts = group.get("review_artifacts")
        require(isinstance(artifacts, dict), f"review_artifacts_missing:{group.get('group_id')}")
        for path in artifacts.values():
            require(Path(path).is_file(), f"review_artifact_missing:{path}")
        rows = group.get("tokens")
        require(isinstance(rows, list) and rows, f"group_tokens_invalid:{group.get('group_id')}")
        for token in rows:
            token_id = str(token.get("visual_token_id") or "")
            require(token_id and token_id not in tokens, f"duplicate_token:{token_id}")
            tokens[token_id] = token
            require(token.get("status") == "locked_for_seven_window_resolve_pilot", f"token_not_locked:{token_id}")
            require(token.get("transcript_timing_promoted_to_authority") is False, f"token_promotes_transcript:{token_id}")
            require(token.get("source_review_status") == "locked_from_contact_sheet", f"token_not_source_reviewed:{token_id}")
            require(isinstance(token.get("visual_window"), list), f"window_missing:{token_id}")
            require(len(token.get("position_path") or []) >= 2, f"position_path_missing:{token_id}")
            require(len(token.get("size_path") or []) >= 2, f"size_path_missing:{token_id}")
            require(len(token.get("opacity_path") or []) >= 2, f"opacity_path_missing:{token_id}")
            phases = token.get("animation_phases")
            require(isinstance(phases, dict) and phases.get("classification"), f"animation_phases_missing:{token_id}")
            style = token.get("style_lock")
            require(isinstance(style, dict) and style.get("source_locked") is True, f"style_lock_missing:{token_id}")
            authoritative_fields = {
                key: value
                for key, value in token.items()
                if key not in {"v1_evidence_sources", "v1_visual_window_candidates"}
            }
            serialized = json.dumps(authoritative_fields, ensure_ascii=False).casefold()
            for placeholder in FORBIDDEN_PLACEHOLDERS:
                require(placeholder not in serialized, f"placeholder_found:{token_id}:{placeholder}")

    require(set(tokens) == EXPECTED_TOKEN_IDS, "token_set_invalid")
    require(tokens["vf_01_nineteen"].get("display_text") == "Nineteen", "nineteen_identity_invalid")
    require(tokens["vf_02_decorative_glyph"].get("display_text") == "Just", "already_decoration_unresolved")
    require(tokens["vf_05_decorative_glyph"].get("display_text") == "I", "know_decoration_unresolved")
    require(tokens["vf_04_market"]["visual_window"][1] >= 493, "market_persistence_too_short")
    require(tokens["vf_04_back"]["visual_window"][1] >= 493, "back_persistence_too_short")
    require(tokens["vf_04_their"]["visual_window"][1] >= 496, "their_persistence_too_short")
    require(tokens["vf_06_blocks"]["position_path"][0]["value"][0] > 0.60, "blocks_not_right_aligned")
    require(tokens["vf_07_something"]["animation_phases"]["entrance_window"][0] == 658, "something_entrance_missing")

    next_boundary = manifest.get("next_boundary")
    require(isinstance(next_boundary, dict), "next_boundary_missing")
    require(next_boundary.get("resolve_action_allowed") is True, "resolve_pilot_not_allowed")
    require(next_boundary.get("scope") == "seven_windows_only", "next_scope_invalid")
    require(next_boundary.get("full_rollout_allowed") is False, "full_rollout_allowed")

    result = {
        "task_id": TASK_ID,
        "ok": True,
        "checks": {
            "group_count": 7,
            "visual_token_count": 17,
            "visual_only_component_count": 2,
            "unresolved_component_count": 0,
            "placeholder_count": 0,
            "transcript_timing_promoted_count": 0,
            "resolve_modified": False,
            "seven_window_resolve_pilot_authorized": True,
            "full_rollout_authorized": False,
        },
        "manifest": str(manifest_path),
        "summary": str(summary_path),
    }
    (output_dir / "lock_validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = validate(args.output_dir.resolve())
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {TASK_ID}: {type(exc).__name__}: {exc}")
        return 1
    print(f"PASS {TASK_ID}: groups=7 tokens=17 unresolved=0")
    print(result["manifest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
