from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "analysis" / "build_caption_visual_first_script_renderability_correction_v3.py"
VALIDATOR_PATH = ROOT / "scripts" / "analysis" / "validate_caption_visual_first_script_renderability_correction_v3.py"
BASE_PATH = ROOT / "artifacts" / "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_AUTHORITY_LOCK_V2" / "visual_authority_lock_v2.json"
OUT_PATH = ROOT / "artifacts" / "DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_SCRIPT_RENDERABILITY_CORRECTION_V3" / "visual_authority_script_renderability_v3.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


builder = load_module("script_renderability_builder_v3", BUILDER_PATH)
validator = load_module("script_renderability_validator_v3", VALIDATOR_PATH)


def token_map(authority):
    return {
        token["visual_token_id"]: token
        for group in authority["groups"]
        for token in group["tokens"]
    }


def build():
    builder.build(ROOT)
    return json.loads(OUT_PATH.read_text(encoding="utf-8"))


def test_source_review_corrects_already_decorative_text_identity():
    manifest = build()
    tokens = token_map(manifest)
    assert tokens["vf_02_decorative_glyph"]["display_text"] == "Already"
    assert tokens["vf_02_decorative_glyph"]["text_authority"] == "source_video_visual_review"


def test_know_decorative_identity_remains_single_cursive_i():
    manifest = build()
    assert token_map(manifest)["vf_05_decorative_glyph"]["display_text"] == "I"


def test_two_script_tokens_use_provisional_windows_installed_candidate():
    manifest = build()
    tokens = token_map(manifest)
    for token_id in ("vf_02_decorative_glyph", "vf_05_decorative_glyph"):
        style = tokens[token_id]["style_lock"]
        assert style["font_family"] == "Gabriola"
        assert style["font_style"] == "Regular"
        assert style["font_resolution_status"] == "provisional_renderable_candidate_for_seven_window_visual_review"
        assert style["font_visual_approval_required"] is True
        assert style["font_family_source_locked"] is False


def test_correction_does_not_change_visual_mechanics_or_other_tokens():
    base = json.loads(BASE_PATH.read_text(encoding="utf-8"))
    manifest = build()
    bt = token_map(base)
    mt = token_map(manifest)
    corrected = {"vf_02_decorative_glyph", "vf_05_decorative_glyph"}
    mechanics = ("visual_window", "position_path", "size_path", "opacity_path", "animation_phases", "z_order", "role")
    for token_id in corrected:
        for key in mechanics:
            assert mt[token_id][key] == bt[token_id][key]
    for token_id in set(mt) - corrected:
        assert mt[token_id] == bt[token_id]


def test_katex_script_is_removed_from_corrected_authority():
    manifest = build()
    assert "KaTeX_Script" not in json.dumps(manifest, sort_keys=True)


def test_validator_keeps_full_rollout_blocked_and_pilot_authorized():
    build()
    result = validator.validate(ROOT)
    assert result["ok"] is True
    assert result["checks"]["unresolved"] == 0
    assert result["checks"]["full_rollout_authorized"] is False
    assert result["checks"]["seven_window_resolve_pilot_authorized"] is True
