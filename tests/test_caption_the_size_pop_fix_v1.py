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


def test_runtime_scope_is_exactly_two_size_targets():
    text = (ROOT / "resolve_workspace/modules/caption_the_size_pop_fix_v1.py").read_text(encoding="utf-8")
    assert '"VC_TEXTPLUS_0077_sub_077"' in text
    assert '"VC_TEXTPLUS_0079_sub_079"' in text
    assert '"target_size": 0.089954170778' in text
    assert '"target_size": 0.090976377264' in text
    assert 'TARGET_TIMELINE_NAME = SOURCE_TIMELINE_NAME + "_the_size_fix_v1"' in text
    assert 'visual.write_key(tool, "Size"' in text
    assert 'visual.write_key(tool, "Center"' not in text
    assert 'visual.write_key(tool, "Opacity1"' not in text


def test_runtime_uses_later_direct_source_size_authority():
    plan = json.loads((ROOT / "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_font_size_plan_step_3B_2.json").read_text(encoding="utf-8-sig"))
    rows = {row["name"]: row for row in plan["items"]}
    assert rows["VC_TEXTPLUS_0077_sub_077"]["target_size"] == 0.089954170778
    assert rows["VC_TEXTPLUS_0079_sub_079"]["target_size"] == 0.090976377264
    assert rows["VC_TEXTPLUS_0077_sub_077"]["source_metrics"]["source"] == "caption_style_event"
    assert rows["VC_TEXTPLUS_0079_sub_079"]["source_metrics"]["source"] == "caption_style_event"


def test_preparer_forbids_unrelated_mutations():
    text = (ROOT / "scripts/davinci/prepare_caption_the_size_pop_fix_v1.py").read_text(encoding="utf-8")
    assert '"only_size_mutation_authorized": True' in text
    assert '"center_mutation_authorized": False' in text
    assert '"opacity_mutation_authorized": False' in text
    assert '"style_mutation_authorized": False' in text
    assert '"timing_track_mutation_authorized": False' in text
    assert '"caption_recreation_authorized": False' in text
    assert '"occlusion_mutation_authorized": False' in text


def test_validator_requires_exact_bounded_result():
    mod = load("scripts/davinci/validate_caption_the_size_pop_fix_v1.py", "the_size_validator_test")
    report = {
        "ok": True,
        "source_timeline_name": mod.SOURCE,
        "target_timeline_name": mod.TARGET,
        "final_textplus_count": 114,
        "target_caption_count": 2,
        "size_key_write_count": 21,
        "mutated_property_count": 2,
        "caption_recreation_count": 0,
        "center_write_count": 0,
        "opacity_write_count": 0,
        "style_write_count": 0,
        "timing_track_mutation_count": 0,
        "occlusion_mutation_count": 0,
        "save_call_count": 1,
        "source_timeline_unchanged": True,
        "motion_fade_source_preserved_except_target_size": True,
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
    report["center_write_count"] = 1
    assert mod.validate(report, persistent)["ok"] is False


def test_current_preimage_values_are_intentionally_superseded():
    text = (ROOT / "resolve_workspace/modules/caption_the_size_pop_fix_v1.py").read_text(encoding="utf-8")
    assert '"expected_pre_size": 0.257314286' in text
    assert '"expected_pre_size": 0.247157143' in text
    assert '"target_size": 0.089954170778' in text
    assert '"target_size": 0.090976377264' in text
