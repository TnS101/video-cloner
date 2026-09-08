#!/usr/bin/env python3
"""Validate the Step 3D-V1 visual-first caption-authority pilot artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_AUTHORITY_PILOT_V1"
EXPECTED_GROUP_IDS = (
    "vf_group_01_nineteen_identity",
    "vf_group_02_already_decorated",
    "vf_group_03_stakes_are_high",
    "vf_group_04_knows_market_persistence",
    "vf_group_05_decorated_know",
    "vf_group_06_buildings_blocks_builders",
    "vf_group_07_something_motion",
)
EXPECTED_VISUAL_TEXT = {
    "vf_01_nineteen": "Nineteen",
    "vf_02_already": "already",
    "vf_03_stakes": "stakes",
    "vf_03_are": "are",
    "vf_03_high": "HIGH",
    "vf_04_that": "that",
    "vf_04_knows": "KNOWS",
    "vf_04_market": "market",
    "vf_04_back": "back",
    "vf_04_their": "their",
    "vf_05_know": "know",
    "vf_06_buildings": "buildings",
    "vf_06_blocks": "blocks",
    "vf_06_builders": "builders",
    "vf_07_something": "something",
}


class ValidationError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValidationError(code)


def validate(output_dir: Path) -> dict[str, Any]:
    manifest_path = output_dir / "visual_authority_pilot.json"
    summary_path = output_dir / "PILOT_SUMMARY.md"
    require(manifest_path.is_file(), "manifest_missing")
    require(summary_path.is_file(), "summary_missing")
    manifest = load_json(manifest_path)

    require(manifest.get("task_id") == TASK_ID, "task_id_mismatch")
    require(manifest.get("ok") is True, "manifest_not_ok")
    require(manifest.get("schema") == "video_cloner_caption_visual_first_authority_pilot", "schema_mismatch")
    summary = manifest.get("summary")
    require(isinstance(summary, dict), "summary_invalid")
    require(summary.get("pilot_group_count") == 7, "group_count_not_7")
    require(summary.get("transcript_timing_promoted_count") == 0, "transcript_timing_promoted")
    require(summary.get("resolve_modified") is False, "resolve_modified")
    require(summary.get("full_rollout_authorized") is False, "full_rollout_authorized")

    policy = manifest.get("authority_policy")
    require(isinstance(policy, dict), "authority_policy_invalid")
    require(policy.get("primary_authority") == "source_video_pixels", "primary_authority_not_visual")
    require(
        policy.get("transcript_use") == "search_seed_and_canonical_text_fallback_only",
        "transcript_use_invalid",
    )

    groups = manifest.get("groups")
    require(isinstance(groups, list), "groups_invalid")
    require(tuple(group.get("group_id") for group in groups) == EXPECTED_GROUP_IDS, "group_ids_mismatch")

    tokens: dict[str, dict[str, Any]] = {}
    contact_sheet_count = 0
    overlay_sheet_count = 0
    source_evidence_count = 0
    visual_only_count = 0
    for group in groups:
        require(group.get("authority") == "source_video_pixels_and_source_derived_visual_evidence", "group_authority_invalid")
        require(group.get("search_seed_authority") == "transcript_search_seed_only", "search_seed_authority_invalid")
        require(isinstance(group.get("reported_failures"), list) and group["reported_failures"], "reported_failures_missing")
        require(isinstance(group.get("visual_tokens"), list) and group["visual_tokens"], "visual_tokens_missing")
        require(isinstance(group.get("context_timeline_window"), list), "context_window_missing")
        review = group.get("review_artifacts")
        require(isinstance(review, dict), "review_artifacts_missing")
        source_sheet = Path(str(review.get("source_contact_sheet") or ""))
        overlay_sheet = Path(str(review.get("overlay_contact_sheet") or ""))
        frame_evidence = Path(str(review.get("frame_evidence") or ""))
        require(source_sheet.is_file() and source_sheet.stat().st_size > 0, "source_contact_sheet_missing")
        require(overlay_sheet.is_file() and overlay_sheet.stat().st_size > 0, "overlay_contact_sheet_missing")
        require(frame_evidence.is_file() and frame_evidence.stat().st_size > 0, "frame_evidence_missing")
        contact_sheet_count += 1
        overlay_sheet_count += 1
        source_evidence_count += int(group.get("source_evidence_count") or 0)
        for token in group["visual_tokens"]:
            token_id = str(token.get("visual_token_id") or "")
            require(token_id and token_id not in tokens, f"duplicate_or_missing_token:{token_id}")
            tokens[token_id] = token
            require(token.get("transcript_timing_promoted_to_authority") is False, f"token_promotes_transcript:{token_id}")
            require(token.get("visual_window_authority") != "transcript", f"token_window_transcript_authority:{token_id}")
            for legacy in token.get("legacy_transcript_first_state") or []:
                require(legacy.get("authoritative") is False, f"legacy_state_authoritative:{token_id}")
            if token.get("visual_kind") != "text" or token.get("text_authority") == "visual_only":
                visual_only_count += 1

    require(set(EXPECTED_VISUAL_TEXT).issubset(tokens), "expected_visual_tokens_missing")
    for token_id, display_text in EXPECTED_VISUAL_TEXT.items():
        require(tokens[token_id].get("display_text") == display_text, f"display_text_mismatch:{token_id}")

    require(tokens["vf_01_nineteen"].get("display_text") == "Nineteen", "nineteen_visual_identity_missing")
    require(tokens["vf_01_nineteen"].get("text_authority") == "user_visual_evidence", "nineteen_authority_invalid")
    require(tokens["vf_02_decorative_glyph"].get("visual_kind") == "decoration", "already_decoration_missing")
    require(tokens["vf_05_decorative_glyph"].get("visual_kind") == "decoration", "know_decoration_missing")

    group4 = next(group for group in groups if group["group_id"] == "vf_group_04_knows_market_persistence")
    group4_ids = {token["visual_token_id"] for token in group4["visual_tokens"]}
    require({"vf_04_market", "vf_04_back", "vf_04_their"}.issubset(group4_ids), "persistence_tokens_missing")
    group6 = next(group for group in groups if group["group_id"] == "vf_group_06_buildings_blocks_builders")
    require(
        group6.get("expected_layer_order") == ["vf_06_buildings", "vf_06_blocks", "vf_06_builders"],
        "buildings_blocks_builders_order_invalid",
    )

    next_boundary = manifest.get("next_boundary")
    require(isinstance(next_boundary, dict), "next_boundary_missing")
    require(next_boundary.get("requires_user_visual_approval") is True, "visual_approval_not_required")
    require(next_boundary.get("resolve_action_allowed") is False, "resolve_action_incorrectly_allowed")

    require(contact_sheet_count == 7, "source_contact_sheet_count_not_7")
    require(overlay_sheet_count == 7, "overlay_contact_sheet_count_not_7")
    require(source_evidence_count > 0, "no_source_visual_evidence")
    require(visual_only_count >= 2, "visual_only_components_missing")

    validation = {
        "task_id": TASK_ID,
        "ok": True,
        "checks": {
            "group_count": 7,
            "visual_token_count": len(tokens),
            "visual_only_component_count": visual_only_count,
            "source_evidence_record_count": source_evidence_count,
            "source_contact_sheet_count": contact_sheet_count,
            "overlay_contact_sheet_count": overlay_sheet_count,
            "transcript_timing_promoted_count": 0,
            "resolve_modified": False,
            "full_rollout_authorized": False,
        },
        "manifest": str(manifest_path),
        "summary": str(summary_path),
    }
    (output_dir / "pilot_validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return validation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validation = validate(args.output_dir.resolve())
    except Exception as exc:  # noqa: BLE001 - terminal CLI report
        print(f"FAIL {TASK_ID}: {type(exc).__name__}: {exc}")
        return 1
    checks = validation["checks"]
    print(
        "PASS "
        f"{TASK_ID}: groups={checks['group_count']} "
        f"tokens={checks['visual_token_count']} "
        f"visual_only={checks['visual_only_component_count']} "
        f"evidence={checks['source_evidence_record_count']}"
    )
    print(validation["manifest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
