"""Validate the visual-first script renderability authority correction V3."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3"
BASE_TASK_ID = "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_AUTHORITY_LOCK_V2"
BASE_PATH = "artifacts/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_AUTHORITY_LOCK_V2/visual_authority_lock_v2.json"
MANIFEST_PATH = "artifacts/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3/visual_authority_script_renderability_v3.json"
VALIDATION_PATH = "artifacts/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3/script_renderability_validation.json"


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def tokens(authority: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result = {}
    for group in authority.get("groups") or []:
        for token in group.get("tokens") or []:
            result[str(token.get("visual_token_id"))] = token
    return result


def validate(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    base = load_json(root / BASE_PATH)
    manifest = load_json(root / MANIFEST_PATH)
    require(base.get("task_id") == BASE_TASK_ID and base.get("ok") is True, "base")
    require(manifest.get("task_id") == TASK_ID and manifest.get("ok") is True, "identity")

    summary = manifest.get("summary") or {}
    require(summary.get("group_count") == 7, "group_count")
    require(summary.get("visual_token_count") == 17, "token_count")
    require(summary.get("visual_only_component_count") == 2, "visual_only_count")
    require(summary.get("unresolved_component_count") == 0, "unresolved")
    require(summary.get("placeholder_count") == 0, "placeholder")
    require(summary.get("transcript_timing_promoted_count") == 0, "transcript_timing")
    require(summary.get("visual_text_correction_count") == 1, "text_correction_count")
    require(summary.get("provisional_script_font_candidate_count") == 2, "font_candidate_count")
    require(summary.get("full_rollout_authorized") is False, "full_rollout")

    boundary = manifest.get("next_boundary") or {}
    require(boundary.get("resolve_action_allowed") is True, "resolve_action")
    require(boundary.get("scope") == "seven_windows_only", "scope")
    require(boundary.get("full_rollout_allowed") is False, "full_rollout_boundary")
    require(boundary.get("script_font_family_is_provisional") is True, "provisional_boundary")

    bt = tokens(base)
    mt = tokens(manifest)
    require(set(bt) == set(mt) and len(mt) == 17, "token_identity")

    expected = {
        "vf_02_decorative_glyph": "Already",
        "vf_05_decorative_glyph": "I",
    }
    mechanics = ("visual_window", "position_path", "size_path", "opacity_path", "animation_phases", "z_order", "role")
    for token_id, display_text in expected.items():
        token = mt[token_id]
        style = token.get("style_lock") or {}
        require(token.get("display_text") == display_text, f"display_text:{token_id}")
        require(token.get("visual_kind") == "visual_only_text_decoration", f"kind:{token_id}")
        require(style.get("font_class") == "high_contrast_script", f"font_class:{token_id}")
        require(style.get("font_family") == "Gabriola", f"font_family:{token_id}")
        require(style.get("font_style") == "Regular", f"font_style:{token_id}")
        require(style.get("font_resolution_status") == "provisional_renderable_candidate_for_seven_window_visual_review", f"font_status:{token_id}")
        require(style.get("font_family_source_locked") is False, f"font_source_lock:{token_id}")
        require(style.get("font_visual_approval_required") is True, f"font_visual_approval:{token_id}")
        for key in mechanics:
            require(token.get(key) == bt[token_id].get(key), f"mechanics:{token_id}:{key}")

    for token_id in sorted(set(mt) - set(expected)):
        require(mt[token_id] == bt[token_id], f"unrelated_token_changed:{token_id}")

    serialized = json.dumps(manifest, sort_keys=True)
    require("KaTeX_Script" not in serialized, "unsafe_katex_family_retained")

    result = {
        "ok": True,
        "task_id": TASK_ID,
        "checks": {
            "groups": 7,
            "tokens": 17,
            "visual_only": 2,
            "text_corrections": 1,
            "provisional_script_fonts": 2,
            "unresolved": 0,
            "transcript_timing_promoted": 0,
            "full_rollout_authorized": False,
            "seven_window_resolve_pilot_authorized": True,
        },
        "manifest": MANIFEST_PATH,
    }
    write_json(root / VALIDATION_PATH, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    print(json.dumps(validate(args.root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
