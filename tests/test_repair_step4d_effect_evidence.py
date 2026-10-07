import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/repair_step4d_effect_evidence.py"
MANIFEST = ROOT / "tests/fixtures/step4d_effect_evidence_repair_cases.json"
SPEC = importlib.util.spec_from_file_location("step4d_effect_repair", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_bounded_effect_evidence_repair_is_fail_closed_and_generic():
    artifacts = MODULE.build(MANIFEST)
    contract = json.loads(artifacts["step4d_effect_evidence_repair_contract.json"])
    validation = json.loads(artifacts["step4d_effect_evidence_repair_validation.json"])
    before_after = json.loads(artifacts["step4d_effect_evidence_before_after.json"])
    post = json.loads(artifacts["step4d_effect_evidence_validity_after_repair.json"])

    assert validation["result"] == "PASS_STEP_4D_BOUNDED_EFFECT_EVIDENCE_REPAIR_READY_FOR_HUMAN_REVIEW"
    assert validation["freeze_integrity"]["status"] == "PASS"
    assert validation["bounded_case_count"] == len(contract["cases"]) == 11
    assert validation["upstream_glyph_authority_changed"] is False
    assert validation["upstream_glyph_sha256_before"] == validation["upstream_glyph_sha256_after"]
    assert validation["production_hardcoded_identities"] == []
    assert validation["good_control_regression"] is False
    assert before_after["cases_degraded"] == 0
    assert post["gate_run_count"] == 1
    assert all(row["new_validity"] in MODULE.VALIDITY for row in contract["cases"])
    assert all(row["new_validity"] == "INSUFFICIENT_EVIDENCE" for row in contract["cases"] if row["effect_class"] == "caption_occlusion")
    assert all(row["temporal_evidence"]["status"] != "TEMPORAL_CLIP_EVIDENCE_SUPPORTED" for row in contract["cases"] if row["effect_class"] == "clipping")
    assert all(row["temporal_evidence"]["status"] == "TEMPORAL_CLIP_EVIDENCE_UNRESOLVED" for row in contract["cases"] if row["effect_class"] == "clipping" and row["new_validity"] == "INVALID_FOR_EFFECT")
    promoted = [row for row in contract["cases"] if row["old_validity"] == "INVALID_FOR_EFFECT" and row["new_validity"] in {"VALID_FOR_EFFECT", "PARTIAL_BUT_USABLE"}]
    assert all(row["metrics"]["source_mask_agreement"] >= 0.12 and row["metrics"]["contamination_ratio"] <= 0.5 for row in promoted)

    for case in contract["cases"]:
        for frame in case["target_foreground"]["frames"]:
            shape = frame["shape"]
            foreground = MODULE.gate.prior.decode(shape, frame["target_foreground_rle"]) > 0
            exterior = MODULE.gate.prior.decode(shape, frame["exterior_context_rle"]) > 0
            unknown = MODULE.gate.prior.decode(shape, frame["unknown_region_rle"]) > 0
            assert not np.any(foreground & exterior)
            assert not np.any(foreground & unknown)
            assert bool(np.any(unknown)) == (frame["metrics"]["unknown_ratio"] > 0)
