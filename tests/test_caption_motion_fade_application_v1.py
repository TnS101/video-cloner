from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(relative: str, name: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_authority_builder_constants_and_policy():
    mod = load("scripts/analysis/build_caption_motion_fade_authority_v1.py", "motion_authority_test")
    assert mod.EXPECTED_PHYSICAL == 114
    assert mod.EXPECTED_DYNAMIC_REPAIR == 4
    assert mod.EXPECTED_PROTECTED_EXITS == 3
    assert mod.EXPECTED_TOTAL_EXITS == 4
    assert mod.VF_NORMALIZED_SHA256 == "6f7cdf265dcb18611e7f6326d7d12de7a3dade7b2a7b6d33e1d406d5645ca6f5"


def test_runtime_has_bounded_scope_constants():
    text = (ROOT / "resolve_workspace/modules/caption_motion_fade_application_v1.py").read_text(encoding="utf-8")
    assert 'EXPECTED_CENTER_TARGETS = 7' in text
    assert 'EXPECTED_OPACITY_TARGETS = 17' in text
    assert 'ALLOWED_PROPERTIES = {"Center", *OPACITY_INPUTS}' in text
    assert 'TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_motion_fade_v1"' in text
    assert "caption_recreation_count" in text
    assert "size_write_count" in text
    assert "style_write_count" in text
    assert "occlusion_mutation_count" in text


def test_runtime_does_not_authorize_size_or_text_writes():
    text = (ROOT / "resolve_workspace/modules/caption_motion_fade_application_v1.py").read_text(encoding="utf-8")
    assert 'write_dense(tool, input_name' in text
    assert 'input_name == "Center"' in text
    assert 'OPACITY_INPUTS = ("Opacity1", "Opacity2", "Opacity3")' in text
    assert 'write_dense(tool, "Size"' not in text
    assert 'write_dense(tool, "StyledText"' not in text


def test_preparer_locks_detector_opacity_and_non_target_layers():
    text = (ROOT / "scripts/davinci/prepare_caption_motion_fade_application_v1.py").read_text(encoding="utf-8")
    assert '"repair_caption_opacity_authorized": False' in text
    assert '"size_mutation_authorized": False' in text
    assert '"style_mutation_authorized": False' in text
    assert '"caption_recreation_authorized": False' in text
    assert '"occlusion_mutation_authorized": False' in text


def test_validator_requires_persistent_idempotent_one_save():
    mod = load("scripts/davinci/validate_caption_motion_fade_application_v1.py", "motion_validator_test")
    report = {
        "ok": True,
        "source_timeline_name": mod.SOURCE,
        "target_timeline_name": mod.TARGET,
        "final_textplus_count": 114,
        "center_target_count": 7,
        "opacity_target_count": 17,
        "caption_recreation_count": 0,
        "size_write_count": 0,
        "style_write_count": 0,
        "occlusion_mutation_count": 0,
        "save_call_count": 1,
        "source_timeline_unchanged": True,
        "v4_occlusion_preserved": True,
        "persistent_readback_ok": True,
        "idempotency_ok": True,
        "visual_approval_required": True,
        "further_rollout_authorized": False,
    }
    persistent = {
        "ok": True,
        "checks": {"a": True, "b": True},
        "visual_approval_required": True,
        "further_rollout_authorized": False,
    }
    assert mod.validate(report, persistent)["ok"] is True
    report["save_call_count"] = 2
    assert mod.validate(report, persistent)["ok"] is False


def test_b33_accepted_artifact_points_to_motion_fade_boundary():
    path = ROOT / "artifacts/DZSQH7AUHJT_STEP_3B3_OUTLINE_SHADOW_AUTHORITY_RECONCILIATION_V2/effective_authority_validation.json"
    if not path.is_file():
        return
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    assert data["ok"] is True
    assert data["decision"]["next_boundary"] == "caption_motion_fade_application"
    assert data["decision"]["step_3B3_status"] == "complete_no_mutation_required"
