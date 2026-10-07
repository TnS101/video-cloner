import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/investigate_step4d_caption_occlusion.py"
SELECTION = ROOT / "tests/fixtures/step4d_effect_evidence_repair_cases.json"
SPEC = importlib.util.spec_from_file_location("step4d_caption_occlusion", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_caption_occlusion_adjudication_is_bounded_deterministic_and_fail_closed():
    first = MODULE.build(SELECTION)
    second = MODULE.build(SELECTION)
    assert first == second

    evidence = json.loads(first["step4d_caption_occlusion_evidence.json"])
    validation = json.loads(first["step4d_caption_occlusion_validation.json"])

    assert validation["result"] == "PASS_STEP_4D_CAPTION_OCCLUSION_UNSUPPORTED_CURRENT_EVIDENCE_READY_FOR_HUMAN_REVIEW"
    assert validation["freeze_integrity"]["status"] == validation["shadow_freeze_status"] == "PASS"
    assert validation["bounded_candidate_count"] == len(evidence["cases"]) == 3
    assert validation["missing_pixels_only_positive_count"] == 0
    assert validation["unknown_preserved"] is True
    assert validation["production_hardcoded_identities"] == []
    assert validation["upstream_artifacts_changed"] is validation["step2e_changed"] is validation["glyph_masks_changed"] is False
    assert validation["shadow_changed"] is validation["clipping_changed"] is validation["new_segmentation_added"] is False
    assert validation["occlusion_renderer_added"] is validation["resolve_mutated"] is False
    assert validation["step5_started"] is validation["step6_started"] is False
    assert evidence["class_level_verdict"] == "UNSUPPORTED_WITH_CURRENT_EVIDENCE"
    assert evidence["negative_control"]["result"] == "PASS_MISSING_PIXELS_DID_NOT_PROVE_OCCLUSION"
    assert evidence["historical_positive_control"]["result"] == "PASS_HISTORICAL_ACCEPTED_OWNED_MASK_OVERLAP_RECOGNIZED"
    assert all(row["verdict"] == "UNSUPPORTED_WITH_CURRENT_EVIDENCE" for row in evidence["cases"])
    assert all(row["candidate_occluder_region"]["ownership"] == "OWNERSHIP_UNRESOLVED" for row in evidence["cases"])
    assert all(row["z_order"]["relation"] == "NO_FRONT_BACK_PROOF" for row in evidence["cases"])
