from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "resolve_workspace/modules/step_3B3_outline_shadow_authority_v2.py"


def load_module():
    spec = importlib.util.spec_from_file_location("vc_step3b3_authority_v2_test", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_authority_v2_is_offline_no_mutation_contract():
    module = load_module()
    report = module.build_report(ROOT)
    assert report["ok"] is True
    assert report["textplus_count"] == 114
    assert report["historical_authority"]["stale_mismatch_count"] == 2
    assert report["historical_authority"]["stale_mismatch_signature"] == [
        ["VC_TEXTPLUS_0052_sub_052", "Enabled2", 1.0, 0.0],
        ["VC_TEXTPLUS_0052_sub_052", "Enabled3", 1.0, 0.0],
    ]
    assert report["effective_authority"]["mismatch_count"] == 0
    assert report["effective_authority"]["audit_ok"] is True
    assert report["stronger_later_authority"]["come_source_frame_style"]["Enabled2"] == 0.0
    assert report["stronger_later_authority"]["come_source_frame_style"]["Enabled3"] == 0.0
    assert report["decision"]["step_3B3_status"] == "complete_no_mutation_required"
    assert report["decision"]["timeline_mutation_required"] is False
    assert report["decision"]["resolve_invocations_required"] == 0
    assert report["decision"]["save_calls_required"] == 0
    assert report["decision"]["new_timeline_required"] is False


def test_visual_correction_source_contains_explicit_later_come_effect_lock():
    source = (ROOT / "resolve_workspace/modules/step_3D_visual_instance_correction.py").read_text(encoding="utf-8-sig")
    assert "These values intentionally supersede the visually rejected" in source
    assert "Step 3B fill/outline estimate for this one proof boundary" in source
    tree = ast.parse(source)
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "COME_SOURCE_FRAME_STYLE" for target in node.targets)
    )
    assert isinstance(assignment.value, ast.Dict)


def test_historical_full_step3b3_is_explicitly_older_mutating_authority():
    module = load_module()
    historical = module.load_json(ROOT / module.HISTORICAL_FULL_RELATIVE)
    come = module._historical_come_row(historical)
    assert come["modified"] is True
    assert come["write"]["write_count"] == 19
    assert come["verified_required_input_count"] == 14
    assert come["verified_optional_input_count"] == 3
