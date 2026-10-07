import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/adjudicate_step4d_clipping_final.py"
SELECTION = ROOT / "tests/fixtures/step4d_source_effect_adjudication_cases.json"
SPEC = importlib.util.spec_from_file_location("step4d_clipping_final", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_final_clipping_adjudication_is_bounded_fail_closed_and_closure_ready():
    first = MODULE.build(SELECTION)
    assert first == MODULE.build(SELECTION)
    adjudication = json.loads(first["step4d_clipping_final_adjudication.json"])
    validation = json.loads(first["step4d_clipping_validation.json"])
    matrix = json.loads(first["step4d_effect_class_final_matrix.json"])
    deferred = json.loads(first["step4d_deferred_required_capabilities.json"])

    assert validation["result"] == "PASS_STEP_4D_FINAL_CLIPPING_ADJUDICATION_AND_CLOSURE_READINESS_READY_FOR_HUMAN_REVIEW"
    assert validation["freeze_integrity"]["status"] == validation["shadow_freeze_status"] == "PASS"
    assert validation["occlusion_adjudication_status"] == "PASS_UNCHANGED"
    assert validation["bounded_case_count"] == len(adjudication["cases"]) == 3
    assert validation["negative_controls_remain_negative"] is True
    assert validation["source_observed_known_missing_pixel_count"] == 0
    assert validation["unknown_preserved"] is True
    assert validation["production_hardcoded_identities"] == []
    assert validation["upstream_artifacts_changed"] is validation["occlusion_changed"] is validation["shadow_changed"] is False
    assert validation["new_segmentation_added"] is validation["clipping_renderer_added"] is validation["resolve_mutated"] is False
    assert validation["step5_started"] is validation["step6_started"] is validation["step4d_frozen"] is False
    assert adjudication["class_verdict"] == "UNSUPPORTED_WITH_CURRENT_EVIDENCE"
    assert len(adjudication["negative_control_identities"]) == 2 and len(adjudication["unsupported_identities"]) == 1
    assert matrix["current_version_closure_ready"] is True
    assert matrix["classes"]["caption_occlusion"]["status"] == "UNSUPPORTED_WITH_CURRENT_EVIDENCE"
    capabilities = {row["id"]: row for row in deferred["capabilities"]}
    assert set(capabilities) == {"CAPTION_CLIPPING_DETECTION_V2", "CAPTION_OCCLUSION_DETECTION_V2"}
    assert all(row["status"] == "DEFERRED_REQUIRED_CAPABILITY" for row in capabilities.values())
    assert all(row["required_before"] == "FINAL_PARITY / RELEASE ACCEPTANCE" for row in capabilities.values())
    assert matrix["classes"]["clipping"]["product_level_deferred_requirement"] == "CAPTION_CLIPPING_DETECTION_V2"
    assert set(matrix["long_term_product_capability_status"]) == set(capabilities)
    assert validation["required_deferred_capabilities"] == ["CAPTION_CLIPPING_DETECTION_V2", "CAPTION_OCCLUSION_DETECTION_V2"]

    all_true = dict.fromkeys(adjudication["cases"][0]["conditions"], True)
    assert MODULE.clipping_verdict(all_true, False, True) == "SOURCE_REQUIRED_CLIPPING"
    all_true["boundary_changes_temporally"] = False
    assert MODULE.clipping_verdict(all_true, False, False) == "UNSUPPORTED_WITH_CURRENT_EVIDENCE"
    assert MODULE.clipping_verdict(all_true, True, True) == "NOT_SOURCE_REQUIRED_CLIPPING"
