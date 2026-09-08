"""Build a corrected visual-first authority for the seven-window pilot.

This correction does not alter visual timing, geometry, animation, z-order,
or transcript authority. It corrects the visually reviewed script decoration
identity for group 02 and replaces the uninstalled KaTeX_Script runtime family
with an explicitly provisional Windows-installed script candidate. Full rollout
remains forbidden until the seven-window visual review passes.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict

TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3"
BASE_TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_AUTHORITY_LOCK_V2"
DEFAULT_CONTRACT = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_visual_first_script_renderability_correction_v3.json"
DEFAULT_BASE = "artifacts/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_AUTHORITY_LOCK_V2/visual_authority_lock_v2.json"
DEFAULT_BASE_VALIDATION = "artifacts/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_AUTHORITY_LOCK_V2/lock_validation.json"
DEFAULT_OUTPUT = "artifacts/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3"
OUTPUT_MANIFEST = "visual_authority_script_renderability_v3.json"


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def token_map(authority: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for group in authority.get("groups") or []:
        for token in group.get("tokens") or []:
            token_id = str(token.get("visual_token_id") or "")
            require(token_id and token_id not in rows, f"token_identity:{token_id}")
            rows[token_id] = token
    return rows


def build(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    contract_path = root / DEFAULT_CONTRACT
    base_path = root / DEFAULT_BASE
    base_validation_path = root / DEFAULT_BASE_VALIDATION
    output_dir = root / DEFAULT_OUTPUT

    contract = load_json(contract_path)
    base = load_json(base_path)
    base_validation = load_json(base_validation_path)

    require(contract.get("task_id") == TASK_ID, "contract_task")
    require(base.get("task_id") == BASE_TASK_ID and base.get("ok") is True, "base_authority")
    require(base_validation.get("ok") is True, "base_validation")

    summary = base.get("summary") or {}
    require(summary.get("group_count") == 7, "base_group_count")
    require(summary.get("visual_token_count") == 17, "base_token_count")
    require(summary.get("visual_only_component_count") == 2, "base_visual_only_count")
    require(summary.get("unresolved_component_count") == 0, "base_unresolved")
    require(summary.get("placeholder_count") == 0, "base_placeholders")
    require(summary.get("transcript_timing_promoted_count") == 0, "base_transcript_timing")

    corrected = copy.deepcopy(base)
    corrected["schema"] = "video_cloner_caption_visual_first_authority_script_renderability"
    corrected["schema_version"] = 3
    corrected["task_id"] = TASK_ID

    policy = copy.deepcopy(corrected.get("authority_policy") or {})
    policy.update(contract.get("policy") or {})
    corrected["authority_policy"] = policy

    tokens = token_map(corrected)
    base_tokens = token_map(base)
    corrections = contract.get("corrections") or []
    require(len(corrections) == 2, "correction_count")

    corrected_ids = []
    text_correction_count = 0
    for row in corrections:
        token_id = str(row.get("visual_token_id") or "")
        require(token_id in tokens, f"correction_token:{token_id}")
        token = tokens[token_id]
        base_token = base_tokens[token_id]
        require(token.get("visual_kind") == "visual_only_text_decoration", f"correction_kind:{token_id}")
        require(token.get("transcript_timing_promoted_to_authority") is False, f"correction_transcript:{token_id}")
        old_text = str(token.get("display_text") or "")
        new_text = str(row.get("display_text") or "")
        require(new_text, f"correction_text:{token_id}")
        token["display_text"] = new_text
        token["text_authority"] = "source_video_visual_review"
        if old_text != new_text:
            text_correction_count += 1

        style = copy.deepcopy(token.get("style_lock") or {})
        require(style.get("font_class") == row.get("font_class") == "high_contrast_script", f"font_class:{token_id}")
        style["font_family"] = row.get("font_family")
        style["font_style"] = row.get("font_style")
        style["font_resolution_status"] = row.get("font_resolution_status")
        style["font_family_source_locked"] = False
        style["font_visual_class_source_locked"] = True
        style["font_visual_approval_required"] = True
        style["font_renderability_evidence"] = copy.deepcopy(row.get("renderability_evidence"))
        token["style_lock"] = style
        token["font_correction_evidence"] = {
            "text_correction_reason": row.get("text_correction_reason"),
            "source_frame_window": row.get("source_frame_window"),
            "visual_evidence": row.get("visual_evidence"),
        }
        token["status"] = "locked_geometry_timing_with_provisional_renderable_script_font"
        corrected_ids.append(token_id)

        # The correction must not alter any visual mechanics.
        for key in ("visual_window", "position_path", "size_path", "opacity_path", "animation_phases", "z_order", "role"):
            require(token.get(key) == base_token.get(key), f"mechanics_changed:{token_id}:{key}")

    require(sorted(corrected_ids) == ["vf_02_decorative_glyph", "vf_05_decorative_glyph"], "corrected_ids")
    require(text_correction_count == 1, "text_correction_count")

    corrected_summary = copy.deepcopy(summary)
    corrected_summary.update(
        {
            "visual_text_correction_count": 1,
            "provisional_script_font_candidate_count": 2,
            "unresolved_component_count": 0,
            "placeholder_count": 0,
            "transcript_timing_promoted_count": 0,
            "seven_window_resolve_pilot_authorized": True,
            "full_rollout_authorized": False,
            "resolve_modified": False,
        }
    )
    corrected["summary"] = corrected_summary
    corrected["inputs"] = {
        "base_authority": DEFAULT_BASE,
        "base_authority_semantic_sha256": base.get("semantic_sha256"),
        "base_validation": DEFAULT_BASE_VALIDATION,
        "correction_contract": DEFAULT_CONTRACT,
        "correction_contract_semantic_sha256": canonical_hash(contract),
    }
    corrected["next_boundary"] = {
        "objective": "rerun_disposable_seven_window_resolve_pilot_with_renderable_script_candidate",
        "resolve_action_allowed": True,
        "scope": "seven_windows_only",
        "full_rollout_allowed": False,
        "requires_visual_approval_after_render": True,
        "script_font_family_is_provisional": True,
    }
    corrected.pop("semantic_sha256", None)
    corrected["semantic_sha256"] = canonical_hash(corrected)
    write_json(output_dir / OUTPUT_MANIFEST, corrected)
    return corrected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    manifest = build(args.root)
    print(json.dumps({"ok": True, "task_id": TASK_ID, "semantic_sha256": manifest["semantic_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
