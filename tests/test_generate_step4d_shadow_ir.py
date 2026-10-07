import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/generate_step4d_shadow_ir.py"
SPEC = importlib.util.spec_from_file_location("step4d_shadow_ir", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_bounded_shadow_ir_preserves_positive_and_negative_controls():
    artifacts = MODULE.build()
    contract = json.loads(artifacts["step4d_shadow_ir_contract.json"])
    validation = json.loads(artifacts["step4d_shadow_implementation_validation.json"])
    review = json.loads(artifacts["step4d_shadow_human_review_data.json"])
    by_id = {row["source_identity"]: row for row in contract["shadows"]}

    assert validation["result"] == "PASS_STEP_4D_BOUNDED_SHADOW_IMPLEMENTATION_READY_FOR_HUMAN_REVIEW"
    assert validation["freeze_integrity"]["status"] == "PASS"
    assert contract["cases_with_shadow_authority"] == ["caption_tracklet_0090"]
    assert set(contract["cases_without_shadow_authority"]) == {"caption_tracklet_0026", "caption_tracklet_0013"}
    assert by_id["caption_tracklet_0090"]["offset"]["direction"] == "S"
    assert by_id["caption_tracklet_0090"]["evidence"]["temporal_consistency"] == 1.0
    assert by_id["caption_tracklet_0026"]["authority"] == "NO_SHADOW_AUTHORITY"
    assert "temporal_direction_coherence" in by_id["caption_tracklet_0026"]["evidence"]["gate_failures"]
    assert "multiple_source_observations" in by_id["caption_tracklet_0013"]["evidence"]["gate_failures"]
    assert all(row["strength_or_opacity"]["value"] is None and row["softness_or_blur"]["value"] is None for row in contract["shadows"])
    assert contract["global_propagation"] is validation["global_shadow_propagation"] is False
    assert validation["production_hardcoded_identities"] == []
    assert validation["stroke_used_as_shadow_authority"] is validation["background_promoted_to_shadow"] is False
    assert all(row["human_review_status"] == "PENDING" and row["material_properties_checked"] == MODULE.REVIEW_PROPERTIES for row in review["cases"])


def test_shadow_gate_fails_closed_for_contamination_and_stroke_like_symmetry():
    accepted_case = json.loads(MODULE.build()["step4d_shadow_ir_contract.json"])["shadows"][0]
    adjudication = MODULE.load(MODULE.DEFAULT_ADJUDICATION)
    source_case = next(row for row in adjudication["cases"] if row["identity"] == accepted_case["source_identity"] and row["effect_class"] == "shadow")

    contaminated = json.loads(json.dumps(source_case))
    contaminated["evidence_quality"]["contamination"] = .9
    assert MODULE.shadow_gate(contaminated) == (False, ["acceptable_contamination"])

    symmetric = json.loads(json.dumps(source_case))
    symmetric["effect_metrics"]["median_shadow_directional_anisotropy"] = 0
    assert MODULE.shadow_gate(symmetric) == (False, ["directional_displacement"])
